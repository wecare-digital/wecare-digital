import React, { useCallback, useEffect, useRef } from 'react';
import BrandLockup from './BrandLockup';

/**
 * Global site footer, rendered by _app.tsx on every public page and around the
 * sign-in form. Two constraints shape it:
 *
 * 1. All markup stays inline in the return tree. styled-jsx only attaches its
 *    scoping class to elements it can statically see there, so lifting a column
 *    into a variable or a child component would silently drop every style.
 * 2. Every class is ft- prefixed and the old `ftr` class is gone. The globally
 *    imported src/styles/*.css declares unscoped rules for generic names -
 *    including `.layout ~ .ftr{position:fixed}`, which would turn a footer this
 *    tall into an overlay pinned across the viewport.
 *
 * WHAT THIS FOOTER DELIBERATELY DOES NOT CONTAIN, all on owner instruction:
 *  - No Terms / Privacy / Contact links. Those live in the header dropdown, and
 *    repeating them here would duplicate navigation rather than add anything.
 *  - No copyright or year line. A dated "(c) 2026" reads as stale the moment the
 *    year turns, and nothing here needs it.
 *  - No social icons. The company has no social accounts, so an icon row would
 *    point at profiles that do not exist.
 *  - Nothing on the right-hand side at all. It previously held a text link reading
 *    "WECARE.DIGITAL" pointing at https://wecare.digital - which was both a second
 *    copy of the name already set in the lockup on the left, and, on this site, a
 *    link to the page you were already on. Removed rather than replaced.
 */
const Footer: React.FC = () => {
  const dashRef = useRef<HTMLElement | null>( null );
  const taglineRef = useRef<HTMLParagraphElement | null>( null );

  /**
   * The lime dash draws itself in WHEN IT COMES INTO VIEW, not on page load.
   *
   * The footer sits below the fold on every page, so a load-time CSS animation would
   * play to an empty viewport and be finished before anyone scrolled down to it - the
   * same trap the home page's closing rule documents.
   *
   * THE ANIMATION IS OPT-IN, NOT OPT-OUT, and that inversion is the important part. The
   * CSS below ships the FINAL state (the dash fully drawn). This effect adds .is-armed to
   * hide the start state only once it knows it can animate, then .is-in to play it. So no
   * JS, no IntersectionObserver, or reduced motion all leave the dash simply visible
   * instead of stuck at scaleX(0) - an entrance effect must never be the reason something
   * cannot be seen.
   *
   * classList rather than state, deliberately: this is a visual side-effect that does not
   * change what React renders, so driving the node directly avoids a re-render on scroll.
   */
  useEffect( () => {
    const el = dashRef.current;
    if ( !el ) return undefined;
    if ( typeof IntersectionObserver === 'undefined' ) return undefined;
    if ( window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) return undefined;

    // THE TAGLINE RIDES THE SAME ONE-SHOT REVEAL, on one observer rather than two.
    //
    // It had an animation before and it was the wrong kind: a hover that darkened the text
    // and swept a 2px lime underline in from the left - the same sweep, duration and easing
    // the real footer link rows use, on a <p> with no href, sitting among those links. That
    // is a false affordance, so it was removed.
    //
    // This is the honest version of the same wish. An ENTRANCE says "this line matters"
    // without claiming the line is clickable: it plays once, on arrival, and there is no
    // hover state to invite a click. It also reads as one movement with the lime dash below
    // it rather than as a second effect competing with it.
    //
    // Both nodes take the classes so each keeps its own transition - the dash scales, the
    // tagline rises - but they are driven by the one observer on the dash, which is the
    // lower of the two and therefore the stricter trigger.
    const tag = taglineRef.current;
    el.classList.add( 'is-armed' );
    if ( tag ) tag.classList.add( 'is-armed' );
    const io = new IntersectionObserver(
      /*
       * PLAYS AGAIN EACH TIME THE LINE COMES BACK INTO VIEW. It used to disconnect on the first
       * intersection - "an entrance, not a scroll effect" - and that one line is what made the
       * animation effectively invisible.
       *
       * Measured, which is why this changed: this tagline sits at the very bottom of a 2090px
       * document and CANNOT be scrolled higher than 92% down the viewport, at any width up to
       * 2560x1600. It is never on screen at load. So the only moment it can play is the moment a
       * reader reaches the end of the page - and at that moment they are usually still scrolling.
       * The 0.42s delay plus the 1.15s sweep then finish during the deceleration, once, and
       * io.disconnect() guaranteed there was no second chance for the rest of the page view.
       *
       * Re-arming on exit and replaying on re-entry means scrolling away and back shows it again.
       * WCAG 2.2.2 is not engaged: it governs motion that starts AUTOMATICALLY, and this starts
       * only because the reader scrolled. It is also still bounded - 1.57s per entry, never
       * looping while stationary.
       */
      entries => {
        for ( const entry of entries ) {
          if ( entry.isIntersecting ) {
            el.classList.add( 'is-in' );
            if ( tag ) {
              /* Hand the delay back to the stylesheet. replaySweep pins animation-delay to 0s
               * so a pointer gesture moves immediately; the scroll entrance wants the designed
               * 0.42s so the sweep follows the 560ms rise instead of racing it. Clearing the
               * inline value here means one hover does not permanently retune the entrance. */
              tag.style.animationDelay = '';
              tag.classList.add( 'is-in' );
            }
          } else {
            /* Back to the armed state, ready to replay. Safe to hide: by definition the element
             * is outside the viewport when this runs, so nothing visible changes. */
            el.classList.remove( 'is-in' );
            if ( tag ) tag.classList.remove( 'is-in' );
          }
        }
      },
      /*
       * THRESHOLD 1 ON THE TAGLINE, NOT 0.6 ON THE DASH - and the difference is the reason the
       * owner could not see this animation.
       *
       * It observed .ft-dash, which is 56x3px. threshold:0.6 of a 3px-tall box is 1.8px, so the
       * reveal started the instant the dash grazed the bottom edge of the viewport. Measured on
       * the live site by scrolling in reader-sized increments instead of calling scrollIntoView:
       * it fired with the tagline at y=829 of a 900px viewport on desktop and y=773 of 844 on a
       * phone. The 0.42s delay plus the 1.15s sweep then ran out while the line was still in the
       * bottom eighth of the screen, mid-scroll, so there was nothing left by the time a reader
       * settled on the footer.
       *
       * Raising the rise from 6px to 14px did not fix the report because this is a SECOND,
       * independent defect. The first was "too small to notice"; this is "over before you look".
       *
       * WHY NOT rootMargin, which is the obvious tool. Tried -22% and the animation then never
       * fired at all: at MAXIMUM scroll the dash sits 95% down the viewport and the tagline 92%,
       * on both widths. This line lives at the very bottom of a 2090px document and cannot be
       * scrolled any higher, so any bottom margin over about 5% makes the trigger unreachable.
       * Measuring the element's best-case position is what caught that; the first version of this
       * fix was a worse bug than the thing it fixed.
       *
       * threshold:1 on the tagline fires when the WHOLE LINE is on screen - the earliest moment a
       * reader could actually read it - and it is reachable, because at max scroll the line sits
       * fully inside the viewport. One observer still drives both nodes, so the dash and the line
       * stay one gesture.
       *
       * Every probe that used scrollIntoView was blind to this by construction: block:center puts
       * the element in a position a reader can never reach on this page.
       */
      { threshold: 1 }
    );
    /* Observe the TAGLINE, not the dash. The dash is 3px tall, so any threshold on it resolves
     * to "a pixel or two is visible" and fires at the bottom edge of the screen. The tagline is a
     * real line of text, so threshold:1 on it means something a reader would recognise: the whole
     * sentence is on screen. Classes still go on both nodes - see above - so the two move
     * together; only the trigger moved. */
    io.observe( tag || el );
    return () => io.disconnect();
  }, [] );

  /**
   * REPLAY THE COLOUR SWEEP ON POINTER, on top of the scroll trigger.
   *
   * Owner asked for the effect on hover or click, every time. The scroll trigger stays, so the
   * line still announces itself once on arrival for anyone who never points at it.
   *
   * IT RESTARTS THE ANIMATION, NOT THE ARMED STATE. The obvious implementation is to drop .is-in
   * and re-add it, and that is wrong here: .is-armed without .is-in sets opacity 0 and a 14px
   * offset, so every hover would begin with a frame of the line vanishing. Clearing and restoring
   * the inline `animation` property restarts the keyframes while opacity and transform stay where
   * they are.
   *
   * The reflow between the two writes is load-bearing. Without reading offsetWidth the browser
   * coalesces both style changes into one frame, sees no net change, and the animation does not
   * restart at all - the same trap the footer probe was written to catch on the arming path.
   *
   * NO cursor:pointer, and that is deliberate. This line has no href. A pointer cursor on it is
   * the false affordance that got the old hover-underline removed from this very element, and
   * adding the cursor back to advertise a decorative effect would reintroduce it. Hovering still
   * works; it just does not claim to be a link.
   *
   * NO tabindex either. Making a <p> focusable to reach this by keyboard would add a Tab stop that
   * announces nothing and does nothing - the same reasoning that kept .wt-space out of the tab
   * order. Keyboard and screen-reader users get the scroll-triggered run, which is the same
   * animation.
   */
  const replaySweep = useCallback( () => {
    const tag = taglineRef.current;
    if ( !tag ) return;
    if ( typeof window !== 'undefined' && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) return;
    // Only meaningful once the effect has been armed; before that the CSS has no animation to run.
    if ( !tag.classList.contains( 'is-armed' ) ) return;
    tag.style.animation = 'none';
    void tag.offsetWidth;
    tag.style.animation = '';
    /*
     * THE POINTER REPLAY RUNS WITH NO DELAY, and this line is the whole reason the owner
     * reported the effect as "not showing" after it shipped working.
     *
     * The stylesheet sets `animation:ft-run 1.15s ... .42s`. That 0.42s is right for the
     * SCROLL entrance - it lets the 560ms rise settle so the two read as one arrival - and
     * wrong for a pointer, where there is no rise to wait for. Measured with
     * tools/browser/replaycheck.js: after a click, the first frame of movement landed at
     * +500ms. So a hover shorter than half a second produced no movement whatsoever, and a
     * hover barely longer than that produced movement after the reader had already given up.
     * The animation was running correctly the entire time and was invisible anyway.
     *
     * Worse than dead time: the restart above snaps background-position back to its 100%
     * start, so the old behaviour was a visible jump, then a 420ms freeze, then travel.
     *
     * OVERRIDES THE DELAY LONGHAND, NOT THE SHORTHAND. Re-declaring the whole `animation`
     * inline would have to name the keyframes, and styled-jsx is free to scope
     * `@keyframes ft-run` to a hashed name - it happens not to here, but pinning production
     * behaviour to that is a trap that breaks silently on a build-tool upgrade. Setting the
     * longhand keeps the stylesheet as the single source of the keyframes, the duration and
     * the easing, and changes only the one value that is wrong for this trigger.
     *
     * The inline value is cleared when the observer re-arms on re-entry, so the scroll
     * entrance keeps its designed 0.42s.
     */
    tag.style.animationDelay = '0s';
  }, [] );

  return (
  <footer className="ft-footer">
    <div className="ft-in">
      <div className="ft-grid">
        <div className="ft-brand">
          {/* THE LOCKUP IS THE LINK HOME, and it is `compact`.
              Both are corrections. It used to be a bare <BrandLockup /> - not clickable -
              while the redundant text copy of the name on the right WAS a link, so the
              footer made the wrong element interactive. And it rendered at the header's
              full 60px/23px scale, so the footer signature was exactly as large as the
              page's primary brand; `compact` steps it to 44px/18px, same shape, clear
              hierarchy.
              A plain <a> rather than next/link: styled-jsx does not scope capitalised
              components, and on a trailingSlash export '/' resolves the same either way.
              `.kiro/steering/grahak-os-design.md` records this as a known styled-jsx trap
              rather than an oversight, so the rule is disabled at the site with the reason
              instead of being left as a standing error. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a className="ft-home" href="/" aria-label="WECARE.DIGITAL home">
            <BrandLockup compact />
          </a>
          {/* The tagline carries a hover, on owner instruction: the lime underline sweeps
              in from the left, which is the same gesture the header's menu rows use, so
              the two surfaces answer to one visual language.
              IT IS NOT A LINK, deliberately. There is no destination the owner has
              approved for it, and inventing one would mean a hover that promises a click
              and lands somewhere arbitrary. cursor stays default for that reason. If it
              should become a link later, wrap it in an <a> and the sweep still applies. */}
          {/* THE WHOLE LINE IS ONE TRANSLATABLE NODE, AND "Bharat" IS DELIBERATELY NOT PINNED.
              An earlier pass wrapped the word in data-wc-no-translate to stop the provider
              deciding its fate per language. Measured against the live endpoint, that was
              WRONG, and wrong in the worst place - it broke grammar in every Indic language
              this product is built for. Splitting a sentence around a pinned word assumes the
              word keeps its position through translation. It does not.
              English is subject-verb-object with a preposition BEFORE the noun. Hindi, Bengali,
              Tamil, Telugu, Marathi, Gujarati and Urdu all put the object FIRST and use a
              POSTposition after it. So the whole line translates correctly:
                hi  भारत के लिए विश्वसनीय रोजमर्रा की सेवाएं
                ur  بھارت کے لئے روزمرہ کی قابل اعتماد خدمات
              while the split fragment leaves the postposition stranded at the front and the
              pinned word orphaned at the end, in source order:
                hi  के लिए विश्वसनीय रोजमर्रा की सेवाएं Bharat
              Seven languages checked, seven broken. Arabic produced a dangling bound prefix
              for the same reason: خدمات يومية موثوقة لـ + Bharat.
              The whole line also TRANSLITERATES the name into the reader's own script - भारत,
              ভারতের, భారత్, ભારત, بھارت - which is better than holding it in Latin, not worse.
              The inconsistency the earlier pass worried about turns out to be the provider
              doing the right thing per language.
              What remains is an Arabic-specific artefact: the full sentence comes back as
              "خدمات يومية موثوقة لشركة Bharat", inserting "the company" and keeping Bharat in
              Latin. That is one language's MT quirk, not a reason to break grammar in seven.
              translatecheck.js reports this line under "brand embedded in a translatable
              sentence", which is the correct category for it: reported, never failed. */}
          {/* onMouseEnter and onClick replay the colour sweep - see replaySweep. No href, no
              cursor:pointer and no tabindex: the effect is decorative and must not advertise
              itself as a control. */}
          <p
            className="ft-tagline"
            ref={ taglineRef }
            onMouseEnter={ replaySweep }
            onClick={ replaySweep }
          >Trusted everyday services for Bharat</p>

          {/* The brand dash. Purely decorative, hence aria-hidden and a <span> rather than
              an <hr> - it separates nothing and announcing it would be noise. It is the
              same motif as .home-close-rule on the home page and .wt-lane-bar in the
              workflow panel: a short lime rule, drawn with transform so the reveal is
              compositor-only. Chosen over the alternative of three coloured dots because
              those would have imported the home page's per-subject hues (which carry
              meaning there and none here) and read as a status light.

              IT USED TO SIT IN THE RIGHT-HAND COLUMN, and that was wrong twice over.
              The instruction for this footer was that the right side be blank, and the
              dash was the only thing in it - so the right side was not blank, it held the
              one decorative element on the page. And the bottom-right corner is where the
              fixed support pill lives, so the two shared a space: measured at the end of
              the page, the pill covered 34px of the 56px dash at 1440 and hid it
              ENTIRELY at 768. On phones it cleared by as little as 8px, which flipped to
              an overlap on a taller device.

              Moved inside .ft-brand it closes the brand block it belongs to, the right
              side is genuinely empty, and the collision cannot recur at any width because
              the two objects no longer share a column. */}
          <span className="ft-dash" ref={ dashRef } aria-hidden="true" />
        </div>
      </div>
    </div>

    <style jsx>{`
      /* A hairline above the footer. Without it the footer background is the same #fff as
         the page with nothing between them, so the brand block read as loose content at
         the bottom of the last section rather than as a footer. #eef0e6 is the faint
         warm-neutral the nav dividers use, not a grey that would sit colder than the
         palette.
         The bottom padding keeps the safe-area inset the Capacitor iOS/Android shells
         depend on. */
      .ft-footer{background:#fff;border-top:1px solid #eef0e6;padding:56px 0 40px;padding-bottom:calc(40px + env(safe-area-inset-bottom))}
      .ft-in{max-width:1300px;margin:0 auto;padding:0 24px}

      /* Left-aligned with nothing opposite it, by instruction. Kept as a flex row rather
         than collapsed to a block so that adding a right-hand element later needs no
         structural change.
         justify-content is flex-start, NOT space-between. With space-between and a single
         child nothing moves, but the moment a second element is added it would be flung to
         the right edge - which is the bottom-right corner the fixed support pill occupies,
         and exactly how the dash came to be hidden behind it. Anything added opposite the
         brand needs to clear that corner deliberately rather than inherit a collision. */
      .ft-grid{display:flex;align-items:flex-end;justify-content:flex-start;gap:32px;flex-wrap:wrap}

      .ft-brand{display:flex;flex-direction:column;align-items:flex-start;gap:14px;min-width:0}

      /* inline-flex, not block: a block anchor would stretch to the full measure and give
         the lockup a click target running the width of the page. */
      .ft-home{display:inline-flex;text-decoration:none;border-radius:10px}
      /* OPAQUE #1a3a2a, not the .22 alpha this used to carry. rgba(26,58,42,.22) composites
         to rgb(205,212,208) over the white footer and measures 1.51:1 against it, well under
         the 3:1 WCAG 1.4.11 requires of a focus indicator - the ring was visible to someone
         already looking for it and to nobody else. Opaque on white is 12.48:1.
         The alpha was presumably there to soften the ring; outline-offset already does that
         job by holding it off the lockup, and it does it without spending contrast. */
      .ft-home:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

      /* THE TAGLINE'S COLOUR WAS OFF-PALETTE. It was #9ca3af, a legacy Tailwind grey, which
         rendered the one brand statement on the page as the lightest text in the footer -
         it read as disabled rather than quiet. rgba(0,0,0,.54) is the palette's muted
         value, and is what this file's own notes already recorded as the replacement for
         that family of greys.
         inline-block so the swept underline can span exactly the text, and position
         relative so the ::after anchors to it. */
      /* NO HOVER AFFORDANCE ON THIS LINE, AND THAT IS THE POINT.
         It used to darken to #1a3a2a on hover and sweep a 2px lime underline in from the
         left, with position:relative, display:inline-block and a transition existing only
         to support that. Both are exactly what a link does here - the footer's own rows use
         the same sweep, at the same .2s and the same easing, and the note that used to sit
         below said so outright.
         But this is a <p> with no href. Measured: cursor resolves to auto, there is no
         href attribute, and it sits in the same block as the real footer links. So hovering
         it produced link feedback on text that cannot be clicked - a false affordance, and
         the worst place for one is beside controls that do work.
         The lime accent has not been lost from the footer: .ft-dash below is a 56x3px lime
         rule and is the deliberate, static place for it. A second lime line three pixels
         under the tagline was competing with it anyway.
         If this line should ever become a link, give it an href and the sweep comes back with
         it - the affordance is fine, it just has to be true. */
      /* SIZED ON THE SAME LADDER AS THE LOCKUP, on owner instruction. The brand wordmark
         steps 23px header -> 18px compact (footer) -> 16px compact-mobile; the tagline sits
         one rung under the compact wordmark and steps with it, so the brand line and the
         sentence beneath it read as one block at one scale rather than the tagline floating
         at a flat size independent of the signature above it. 15px -> 16px here, 14px on the
         phone (see the max-width:767px block below), which keeps the same step down from the
         compact wordmark at both widths. */
      .ft-tagline{
        font-size:16px;line-height:1.6;color:rgba(0,0,0,.54);
        margin:0;max-width:340px;
        /* AN ENTRANCE, NOT A HOVER - and that distinction is the whole point.
           The default below is the FINAL state, per the .is-armed pattern this file already
           uses for the dash: opacity 1, no offset. JavaScript adds .is-armed to hide the
           start state only once it knows it can animate, then .is-in plays it. So no JS, no
           IntersectionObserver or reduced motion all leave the line simply readable.
           Same easing as the dash below so the two read as one settling movement, and 24ms
           ahead of it: the words arrive, then the lime rule closes the block under them.
           WHAT THIS DELIBERATELY IS NOT. This line used to darken to #1a3a2a on hover and
           sweep a 2px lime underline in from the left - the footer's real link rows use that
           exact sweep, at the same duration and easing, and they sit in this same block. On a
           <p> with no href that is a false affordance: hover feedback on text that cannot be
           clicked, beside controls that can. An entrance gives the line emphasis without
           claiming it is interactive, because there is no pointer state to invite a click.

           THE RISE IS 14px, NOT 6px, AND THAT WAS A BUG REPORT. The owner said this entrance
           was "not showing" twice. It was: tools/browser/footerprobe.js finds .is-armed
           added, 35 frames of hidden start state painted, 46 frames mid-fade and a finish at
           opacity 1, at both 1280 and 390. It was playing and it was not visible - 6px over
           520ms is about 11px/s, which on a 15px line is roughly the floor of what a reader
           notices while scrolling, especially next to a 56px lime dash drawing beside it.
           Reading the stylesheet said "shipped"; measuring the frames said "invisible", and
           only the second answers the report. 14px is a little over half this line's 24px
           line box, so the movement registers without reading as a jump, and 560ms keeps the
           velocity close to the dash's rather than making the line faster for being farther.
           footerprobe.js asserts the travel, so a future tidy cannot quietly shrink it back. */
        transition:opacity .56s cubic-bezier(.22,.61,.36,1),transform .56s cubic-bezier(.22,.61,.36,1);
      }
      .ft-tagline.is-armed{opacity:0;transform:translateY(14px)}
      .ft-tagline.is-armed.is-in{opacity:1;transform:none}

      /* A COLOUR RUNNING ACROSS THE LINE, ONCE. Owner asked for a colour effect on this line
         "running over" it, so a band of brand green travels left to right through the muted
         text and then the line settles back to flat.

         EVERY PIXEL STAYS READABLE THROUGHOUT, which is the constraint that shaped it. The
         gradient interpolates between only two colours and both are measured on white:

           rgba(0,0,0,.54) -> #757575   4.61:1   the resting colour
           #1a3a2a                     12.48:1   the travelling band

         So the sweep only ever makes the text DARKER than its resting state - contrast rises
         to 12.48:1 at the band and returns to 4.61:1. A lime sweep was the obvious reading of
         "colour" and is exactly what this cannot be: #d1f470 is 1.24:1 on white, so the band
         would have erased the words as it passed over them.

         ONE-SHOT, NOT A LOOP, and that is not a preference. A repeating shimmer is motion that
         starts automatically and runs longer than five seconds, which is WCAG 2.2.2 - the same
         rule that removed this page's terminal loop. It runs once on arrival and stops.

         ADDITIVE, LIKE THE REST OF THIS FILE. background-clip:text needs color:transparent,
         and transparent text with no painted gradient is an INVISIBLE LINE - so the resting
         rules above own the colour, and the two properties that can hide the text are applied
         only under .is-armed.is-in, which JavaScript adds after confirming it can animate. No
         JS, no observer, reduced motion, or a browser without background-clip:text all leave
         the line as plain readable grey.

         background-position is the only animated property and it composites off the main
         thread; animating the gradient stops themselves would relayout the paint on every
         frame. 300% background-size is what gives the band somewhere to travel from. */
      .ft-tagline.is-armed.is-in{
        background-image:linear-gradient(100deg,
          rgba(0,0,0,.54) 42%, #1a3a2a 50%, rgba(0,0,0,.54) 58%);
        background-size:300% 100%;
        background-position:100% 0;
        background-repeat:no-repeat;
        -webkit-background-clip:text;background-clip:text;
        -webkit-text-fill-color:transparent;color:transparent;
        /* Starts after the 560ms rise has settled, so the two read as one arrival rather than
           competing. forwards holds the end state; it runs once and never repeats.

           NEARLY LINEAR EASING, AND THAT IS A CORRECTION. This was
           cubic-bezier(.33,0,.24,1) over 1.5s - the site's standard entrance curve, which
           front-loads its travel. Sampled every 150ms, the band was over the text in only 2
           frames of 12: it crossed in roughly 400ms and then the remaining second held a
           position that was already flat. An easing chosen for "arrive and settle" is wrong for
           a thing whose whole job is to travel at a readable speed.
           This curve is symmetric and close to linear through the middle, so the band moves at
           an even pace for the whole 1.15s instead of darting. */
        animation:ft-run 1.15s cubic-bezier(.45,.05,.55,.95) .42s 1 forwards;
      }
      /* BOTH ENDPOINTS MUST STAY INSIDE 0%..100%, and this is not a tidiness rule - getting it
         wrong hides most of the line.
         A background percentage positions the image as p x (elementWidth - imageWidth). The
         image here is 300% wide, so the origin lands at -2W x p: only p between 0% and 100%
         keeps a 3W-wide image covering the element at all. This animation first ended at -40%,
         which puts the origin at +0.8W - the image then starts four fifths of the way across
         and, with background-repeat:no-repeat, the first 80% of the line has NO gradient behind
         it. Combined with transparent text that is an invisible tagline, permanently, after
         the sweep finishes.
         It looked right: the darkest rendered pixel was identical either way, because the
         fragment that WAS painted carried the correct colour. What gave it away was counting
         ink pixels in a screenshot - 165 against 822 for the same sentence.
         At 100% the element shows the gradient's last third and at 0% its first third; the
         band sits at 42-58%, so both endpoints are flat resting colour and the band is only
         on screen in between. That is what makes the end state indistinguishable from a line
         that never animated. */
      @keyframes ft-run{
        from{background-position:100% 0}
        to{background-position:0% 0}
      }

      /* THE LIME DASH. 56x3px, matching .home-close-rule's 3px lime rule.
         READ THE .is-armed PATTERN BEFORE CHANGING THIS: the default below is the FINAL,
         visible state. .is-armed is added by JavaScript only once it has confirmed it can
         animate, and that is what hides the start state; .is-in then plays the reveal. The
         effect is therefore additive and the dash is never invisible for lack of JS.
         transform:scaleX is the whole animation - compositor-only, so it cannot cause
         layout on any frame the way animating width would. transform-origin:left makes it
         grow from the left edge. align-self keeps it on the tagline's baseline row rather
         than stretched by the flex parent. */
      /* align-self is gone, and its absence is the fix. It was flex-end, which in the old
         right-hand position pinned the dash to the right edge - and below 768px, where
         .ft-grid becomes a column with align-items:flex-start, align-self OVERRODE that and
         kept the dash on the right anyway. That is why the collision with the pill was not
         a desktop-only problem: the dash shared the pill's column at all fourteen widths
         and only vertical distance saved the smaller phones. Inside .ft-brand, with no
         align-self, it simply starts where the lockup and tagline start.
         margin-top sits on top of .ft-brand's 14px gap, so the dash closes the block 18px
         under the tagline - far enough not to be mistaken for the tagline's own hover
         underline, which is lime too and only 2px tall. */
      .ft-dash{
        display:block;
        width:56px;height:3px;margin-top:4px;
        background:#d1f470;border-radius:2px;
        transform-origin:left center;
        transition:transform .62s cubic-bezier(.22,.61,.36,1);
      }
      .ft-dash.is-armed{transform:scaleX(0)}
      .ft-dash.is-armed.is-in{transform:scaleX(1)}

      @media(prefers-reduced-motion:reduce){
        /* The tagline's entrance, neutralised. Scoped to .is-armed so it can actually win:
           the armed rule is (0,2,0) and an unscoped .ft-tagline would be (0,1,0), which is
           the specificity slip the hero's own reduced-motion block had to be corrected for.
           The effect already returns before arming under this preference, so this is the
           guard for the preference changing AFTER the class is on the node. */
        .ft-tagline{transition:none}
        .ft-tagline.is-armed{opacity:1;transform:none}
        /* THE COLOUR SWEEP, AND IT IS NOT ENOUGH TO STOP THE ANIMATION. background-clip:text
           works by making the text itself transparent and painting a gradient through it, so
           animation:none on its own would leave transparent text over a gradient parked off
           the line - an INVISIBLE tagline, for precisely the readers who asked for less
           motion. (No backticks in this comment: it lives inside a styled-jsx template
           literal, and one backtick ends the template - which StyledJsxBackticks.test.tsx
           just caught me doing.)
           Both properties that hide the text have to be handed back, and the resting colour
           restated, because the rule being overridden set it to transparent. Selector is
           (0,3,0) to beat the .is-armed.is-in rule that introduces them. */
        .ft-tagline.is-armed.is-in{
          animation:none;background-image:none;
          -webkit-text-fill-color:currentColor;color:rgba(0,0,0,.54);
        }
        /* Belt and braces. The effect already never arms under reduced motion, so this is
           the guard for the case where the preference changes after arming, when the class
           is already on the node. It kills the movement without hiding the dash. */
        .ft-dash{transition:none}
        .ft-dash.is-armed{transform:scaleX(1)}
      }

      @media(max-width:1024px){
        .ft-footer{padding-top:48px}
      }
      @media(max-width:767px){
        .ft-footer{padding-top:40px}
        .ft-in{padding:0 20px}
        .ft-grid{flex-direction:column;align-items:flex-start;gap:24px}
        /* Tagline steps down with the compact wordmark on the phone (18px -> 16px lockup;
           16px -> 14px here), holding the same one-rung gap it keeps on desktop. */
        .ft-tagline{font-size:14px}
      }
    `}</style>
  </footer>
  );
};

export default Footer;
