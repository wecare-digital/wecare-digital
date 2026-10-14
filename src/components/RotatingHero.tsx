import React, { useEffect, useState } from 'react';
import BrandBadge from './BrandBadge';
import PublicShare from './PublicShare';
import RotatingPill from './RotatingPill';

/**
 * The Home hero — badge, rotating headline pill, one body line — as a reusable,
 * SELF-STYLING component.
 *
 * WHY SELF-STYLING: styled-jsx does not scope composite components. A parent's
 * <style jsx> cannot reach in here, so a consumer passing className or relying on
 * its own rules would get unstyled markup. That is the documented pattern for
 * BrandBadge, BrandLockup and AuthBrand, and it is the only arrangement that works.
 * The consumer owns nothing but the props.
 *
 * WHY A COMPONENT AT ALL, given the sibling warning on the Home page that the
 * rotating markup "MUST stay inline in this return tree": that warning is about
 * lifting markup OUT of a page's own return while leaving the styles behind in the
 * page's <style jsx>. Moving the markup AND its styles together into a component that
 * styles itself is the supported case. The distinction cost a full debugging round on
 * the mega menu, where a renderLink() helper left the rules behind and every row fell
 * through to a global - so it is worth being exact about.
 *
 * Contact, Terms, Privacy, Bharat Rx and Orders all use this. Home, VayuLok and
 * Grahak OS still carry their own inline copies, because their tests pin their class
 * names and CSS strings - so there are FOUR implementations of this hero in the repo
 * (rh-, home-, vl-, hero-), not two. The animation constants here are identical to
 * theirs by construction, and `node tools/browser/animcheck.js` asserts that all four
 * surfaces share the same computed transitions so the family cannot silently drift
 * apart. Measured identical as of this commit:
 *   pill width  0.52s cubic-bezier(.16,1,.3,1)
 *   word        0.42s opacity + transform, same easing
 *   tint        0.52s background-color, same easing
 *   dot         0.5s cubic-bezier(.34,1.56,.64,1) with a .72s delay
 *
 * ANIMATION CONSTANTS - do not retune one surface alone:
 *   2400ms interval, cubic-bezier(.16,1,.3,1) for the wipe and the width glide,
 *   cubic-bezier(.34,1.56,.64,1) .72s for the dot pop, .33em dot with a .18em gap.
 *
 * WORD LENGTH IS LAYOUT. The pill animates to each word's MEASURED width, so the
 * spread between shortest and longest is how far the line's tail travels every tick.
 * The pill sits on its own line here (.rh-head-line is display:block), which makes the
 * headline's line count independent of word width - that was a real defect on Home,
 * where "reflection" pushed the h1 from 75px to 138px at 1440px and the page below
 * jumped 63px every 2400ms. Keep a set within ~2-4 characters anyway, and re-run
 * `node tools/browser/animcheck.js` after changing one.
 *
 * THAT GUARANTEE IS WHY THIS COMPONENT IS THE ONE TO REUSE. The two inline copies that
 * put the pill inline mid-sentence instead - /vayulok/ ("Bharat <pill> Intelligence")
 * and /grahak-os/ ("across <pill>") - still reflow at narrow widths: measured at 320px,
 * VayuLok's h1 is 126px on Weather/Forecast/Heatmap and 87px on Air/Pollen/Solar, and
 * Grahak OS is 168px on WhatsApp against 128px on SMS/Email/Voice. Every surface built
 * on THIS component measures constant at all 21 viewports. Migrating those two pages
 * here is the fix, but it changes their hero line structure, so it is an owner call.
 */

export interface CycleWord {
  word: string;
  /** Pale pill fill. */
  tint: string;
  /** Saturated dot of the same hue. */
  dot: string;
}

interface RotatingHeroProps {
  /**
   * Lime brand pill above the headline. OPTIONAL, and omitting it is a real choice.
   *
   * The home page deliberately REMOVED its own copy of this badge: it rendered the bag mark
   * plus WECARE.DIGITAL only 109px below the header's own lockup, so the brand was stated
   * twice inside 109px and was the first thing anyone read. src/test/BlogDesign.test.tsx pins
   * the same decision for /blog/ - "does not repeat the brand eyebrow".
   * The product and Customer service pages still pass it, because on those the badge names the
   * PRODUCT rather than repeating the company. Where the label would just be the site again,
   * leave it out.
   */
  badgeLabel?: string;
  /** Fixed text on the first headline line. The pill takes the second. */
  frame: string;
  words: CycleWord[];
  /** The single body line under the headline. Optional. */
  sub?: React.ReactNode;
  /** Accessible name for the landmark. */
  ariaLabel: string;
  /** Extra content below the hero, inside the page measure. */
  children?: React.ReactNode;
  /**
   * SUBORDINATE MODE, for a page that already owns its main landmark and its h1.
   *
   * By default this renders <main> and <h1>, which is right when the hero IS the page - the
   * home page, the seven product pages, the five Customer service pages. On a blog post it is not:
   * the article owns the <main> and the post title owns the <h1>, and stacking a second of
   * each produces markup that fails two checks in tools/audit/htmlcheck.js at once -
   * MANY-MAIN at HIGH and H1-MANY - which on the blog would mean 824 pages failing both.
   * Measured in the layout mock before this existed: 2 mains, 2 h1s.
   *
   * With subordinate set, the wrapper becomes a <section> and the headline an <h2>. Nothing
   * visual changes: .rh-head styles by class, not by tag, so the 55px/600 rung is identical
   * either way. What changes is only what the document says it is.
   *
   * NOTE: this flag no longer gates the Subscribe+Share block (that is `noShare` alone now) and
   * is currently unused by any call site - /post/[slug] does not render RotatingHero. It is kept
   * for a future surface that embeds this hero as a section of its own page.
   */
  subordinate?: boolean;
  /**
   * Suppress the Subscribe+Share block for a page that genuinely must not carry it.
   *
   * The block is auto-mounted here for every RotatingHero page, which is right for the marketing
   * and product surfaces AND, since the owner unified the blog onto this one global block, for the
   * blog index and its paginated/topic variants too - BlogIndexView used to pass `noShare` and
   * render its own Subscribe via components/BlogFooterCTA, and now does neither, so the one
   * auto-mounted PublicShare is the blog's only Subscribe+Share.
   *
   * The mount is gated on `!noShare` ALONE (not on `subordinate`): a subordinate page is still a
   * section of someone else's page for landmark/heading purposes, but that no longer suppresses
   * the block. This flag stays as the explicit opt-out for any page that must not carry it.
   */
  noShare?: boolean;
}

const RotatingHero: React.FC<RotatingHeroProps> = ( { badgeLabel, frame, words, sub, ariaLabel, children, subordinate = false, noShare = false } ) => {
  /**
   * 'final' is the CSS default: shutter gone, dot popped, nothing animating. 'armed' puts
   * the start state back, 'shown' plays it. Starting at 'final' is what makes the entrance
   * additive - no JS, a failed bundle or reduced motion all render a complete pill.
   */
  const [ phase, setPhase ] = useState<'final' | 'armed' | 'shown'>( 'final' );

  useEffect( () => {
    // THE ENTRANCE IS OPT-IN, NOT OPT-OUT, and this was a real defect on twelve pages.
    //
    // The shutter used to default to scaleX(1) - a white panel covering the pill's tint - and
    // the dot to scale(0), with .rh-layout.show removing both once this effect had run. So
    // anything that stopped that class arriving left the headline followed by a blank white
    // lozenge with no dot, permanently. Measured on the built /elsewhere/ with scripting
    // disabled: shutter matrix(1,0,0,1,0,0), dot matrix(0,0,0,0,0,0).
    //
    // index.tsx carried the same bug and was fixed; this component was not, so every page
    // using it kept it - the seven product pages and the five Customer service pages.
    //
    // The CSS now ships the FINISHED state and this effect adds .is-armed, which is what puts
    // it back to the start, and only once it knows the animation can play. No JS, a failed
    // bundle or reduced motion therefore all render a complete pill instead of an empty one.
    //
    // classList rather than state: a visual side-effect that changes nothing React renders,
    // which is the case react-hooks/set-state-in-effect exists to steer away from state.
    // DECLARATIVE, NOT classList - AND THAT MATTERS HERE SPECIFICALLY.
    //
    // The closing band on the home page arms itself with classList, which is right there: that
    // node never re-renders. THIS component re-renders every 2400ms, because cycleIndex
    // advances the rotation - and React rewrites className on every render, silently dropping
    // any class added imperatively. Measured: with classList the built page showed
    // "rh-layout show" and no is-armed at all.
    //
    // It still animated, by accident: the first re-render lands at 60ms, which is exactly when
    // is-armed should come off, and because the CSS default is the finished state every later
    // re-render is a no-op. Correct output, for a reason nobody could rely on - adding
    // is-armed to the className template would have broken it.
    //
    // A phase variable makes the class attribute the single source of truth, so the rotation's
    // own re-renders cannot interfere. Scheduled in a timeout rather than set in the effect
    // body because that is the react-hooks/set-state-in-effect case, and because matchMedia is
    // browser-only and must not run during the static export.
    let cancelled = false;
    let reveal = 0;
    const start = window.setTimeout( () => {
      if ( cancelled ) return;
      const reduce = typeof window.matchMedia === 'function'
        && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
      // Stay at 'final': the CSS default is already the finished pill, so there is nothing
      // to do and nothing to animate.
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

  // The landmark and the heading level move together: a subordinate hero is a section of
  // someone else's page, so it must not claim either role. Styling is by class throughout, so
  // the rendered result is pixel-identical - only the semantics differ.
  const Shell = subordinate ? 'section' : 'main';
  const Head = subordinate ? 'h2' : 'h1';

  return (
    <Shell className="rh-shell" aria-label={ ariaLabel }>
      <div className={ [
        'rh-layout',
        phase === 'armed' || phase === 'shown' ? 'is-armed' : '',
        phase === 'shown' ? 'show' : '',
      ].filter( Boolean ).join( ' ' ) }>
        <div className="rh-hero">
          {/* Wrapper carries the spacing. BrandBadge paints itself - styled-jsx
              cannot reach into it from here either. */}
          { badgeLabel && (
            <div className="rh-eyebrow">
              <BrandBadge label={ badgeLabel } />
            </div>
          ) }

          <Head className="rh-head">
            <span className="rh-head-line">{ frame }</span>
            <RotatingPill words={ words } phase={ phase } />
          </Head>

          { sub && <p className="rh-sub">{ sub }</p> }
        </div>

        { children }

        {/* THE SUBSCRIBE + SHARE BLOCK, inside the hero's own content measure (.rh-layout), so it
            aligns with the page content and sits at the content end with no viewport-height void.
            Rendered here means every page that uses RotatingHero (Contact, Terms, Privacy, Bharat
            Rx, the product/service pages) gets one consistent, aligned block.

            GATED ON `!noShare` ONLY, NOT on `subordinate`. The owner unified the blog surfaces
            onto this one global block: /blog (and its paginated/topic variants, via
            BlogIndexView) now WANT the auto-mounted PublicShare rather than their own old
            Subscribe band, so they no longer pass `noShare`. A `subordinate` page is still a
            section of someone else's page for landmark/heading purposes, but that is orthogonal
            to whether it carries the Subscribe+Share block - so the gate is `noShare` alone.
            `noShare` is kept for any page that genuinely must not carry the block. */}
        {/* ONE PAGE-TAIL DOCK. PublicShare owns the same compact Contribute + Subscribe + Share
            icon band on every public surface, including Home. */}
        { !noShare && (
          <div className="rh-tail">
            <PublicShare />
          </div>
        ) }
      </div>

      <style jsx>{`
        /* Font stack declared, not inherited. The declaration stays; the reason this
           comment used to give was wrong. It said the pages rendered in Inter only
           because @aws-amplify/ui-react's styles.css set a family on body, and that
           Pages.css's --font-sans had no Inter in it. Neither is true: Layout.css:116
           sets body to 'Inter', ui-sans-serif, system-ui, … - the value measured in a
           browser on these pages - and Pages.css:60 starts with 'Inter' as well. The
           Amplify stylesheet is not imported globally any more; src/styles/
           amplify-base.css records the seven rules it was really contributing. */
        .rh-shell{
          min-height:calc(100vh - 69px);
          padding-top:108px;
          box-sizing:border-box;
          background:#fff;
          font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          color:#1a1a1a;
        }
        .rh-layout{
          width:100%;max-width:1300px;margin:0 auto;
          padding:80px 24px 48px;box-sizing:border-box;
          display:flex;flex-direction:column;gap:96px;
        }
        /* THE TAIL PAIR - Contribute + Subscribe/Share - is one flex child of .rh-layout, so the
           96px flex gap sits ONCE above the pair, not between the two blocks. Inside, the blocks
           carry their own separators and spacing, so this wrapper adds no gap of its own. */
        .rh-tail{display:flex;flex-direction:column}
        /* align-items:flex-start replaces an align-self on the badge: without it the
           flex default stretches the pill to the full 1300px measure. */
        .rh-hero{display:flex;flex-direction:column;align-items:flex-start}
        .rh-eyebrow{margin:0 0 20px}

        /* Hero h1 rung: 600, LIGHTER than the 700 section level. That inversion is
           notion's and is intentional - the same guard sits on .vl-head and
           .hero-left h1. Do not "correct" it. */
        .rh-head{
          font-size:clamp(36px,4.3vw,60px);font-weight:600;line-height:1.04;
          /* TRACKING IN em, NOT px. A fixed px value against a fluid clamp() font means the
             OPTICAL tightness changes with the viewport: measured across the breakpoints it ran
             -2.22% to -6.11% of the font size, a 2.75x spread, worst at 768-820px where the font
             is still on its 36px floor while the tracking was chosen for 60px. -0.04em is -4% at
             every size, and it lets both media-query overrides go - restating it per breakpoint
             is what caused the spread. index.tsx fixed this; these three copies had not. */
          letter-spacing:-0.04em;color:rgba(0,0,0,.95);margin:0;max-width:900px;
        }
        /* Blocks, so the frame and the pill never share a line. This is what makes the
           h1's height independent of which word is showing. The pill itself (its lozenge,
           dot, width glide, word fade and entrance) lives in RotatingPill, which self-scopes
           its own rp-* CSS - styled-jsx here cannot reach a child component's markup. */
        .rh-head-line{display:block}

        /* The single body rung the contract allows: 20px/400/1.4/-.125px at
           rgba(0,0,0,.898). 560px rather than the headline's 900px, because at 20px a
           900px measure runs to ~110 characters a line, well past the 45-75 the rest
           of the site holds to. text-wrap:balance evens the two lines instead of
           leaving one word orphaned; it is pure progressive enhancement, so it needs
           no @supports guard. */
        .rh-sub{
          font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
          color:rgba(0,0,0,.898);margin:24px 0 0;max-width:560px;text-wrap:balance;
        }

        @media(max-width:767px){
          .rh-shell{min-height:calc(100vh - 85px);padding-top:96px}
          .rh-layout{padding:48px 16px 40px;gap:64px}
          .rh-head{line-height:1.1}
        }
        /* 320px OVERFLOWED BY 11px, and the cause is content rather than layout.
           /contact/ rotates "amend a request" - 279px at the 36px clamp floor - and the pill
           adds ~19px of padding, so the h1 measured 315px inside a 288px measure. Nothing was
           wrong with the box; the widest phrase simply does not fit a 320px screen at 36px.
           32px brings it to ~265px. Scoped to 400px so no other width is retuned, and left as
           a font step rather than clipping the pill, which is the defect this hero was just
           fixed for. */
        @media(max-width:400px){
          .rh-head{font-size:32px}
        }
        /* 280px - Galaxy Fold, folded - still overflowed 7px at 32px, so the step needed a
           second rung rather than a bigger guess. Derived instead of tried: the widest phrase
           on /contact/ is "amend a request" at 279px on the 36px floor, and the pill adds
           ~0.52em of padding, so required width is 279*(F/36) + 0.52F = 8.27F. A 280px
           viewport leaves 248px of measure, giving F <= 30.0px. 28px carries margin for a
           longer phrase being added later, and 280px is the narrowest device that ships. */
        @media(max-width:340px){
          .rh-head{font-size:28px}
        }
        @media(max-width:480px){
        }

      `}</style>
    </Shell>
  );
};

export default RotatingHero;
