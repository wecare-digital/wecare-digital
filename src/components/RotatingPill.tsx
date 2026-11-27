import React, { useEffect, useState } from 'react';
import { createHeroRotationClock } from '../lib/publicHeroRotation';

/**
 * THE ROTATING LIME PILL, EXTRACTED SO EVERY HERO SHARES ONE IMPLEMENTATION.
 *
 * The home hero, the Grahak OS hero, the VayuLok hero and the shared RotatingHero each
 * hand-rolled the SAME mechanism and the SAME CSS: a lime pill in the headline that cycles a
 * word every 2400ms, a dot in the pill's hue, an sr-only copy of the full word list, a width
 * re-measured on resize and font-load so overflow:hidden does not clip a word's tail, and a
 * one-shot entrance (a white shutter wipes off the tint, the dot pops, the first word rises in).
 * Four copies drifted - the width-measure fix had to be ported to each by hand, as the comments
 * in every file record.
 *
 * WHY IT IS SELF-STYLING, AND WHY THAT IS THE WHOLE POINT. styled-jsx scopes a <style jsx> block
 * to the file it compiles in by stamping a hashed class onto that file's own lowercase tags - it
 * CANNOT reach markup rendered by a child component. That is exactly why the four heroes inlined
 * their pill: a host's `.xx-layout.is-armed .xx-mark` rule would never match a `.xx-mark` emitted
 * by a child. So this component owns the pill markup AND all of its CSS (the lozenge, the dot, the
 * width glide, the word fade, and the entrance), with `rp-` prefixed classes scoped here. The host
 * owns only the headline AROUND the pill and drives the entrance by passing `phase`.
 *
 * THE ENTRANCE IS DRIVEN BY `phase`, exactly as RotatingHero's own machine did it. 'final' is the
 * CSS default - the settled pill, which is what a no-JS reader, a failed bundle or reduced motion
 * all get. The host flips to 'armed' (start state put back) then 'shown' (play) once it has
 * confirmed motion is allowed. Starting at 'final' is what makes the entrance ADDITIVE rather than
 * shipping a pill nobody can see.
 *
 * A one-element words array stays static. Multiword heroes cycle continuously.
 * The pill itself is the accessible stop/resume control, without a second
 * visible button. The grid reserves the full word set; reduced motion stays static.
 */

export interface CycleWord {
  word: string;
  /** Pill background tint for this word. */
  tint: string;
  /** Saturated dot of the same hue. */
  dot: string;
}

interface RotatingPillProps {
  words: CycleWord[];
  /**
   * Entrance phase, owned by the host so its one-shot reveal stays in step with the rest of its
   * hero. 'final' (default) is the settled pill; 'armed' puts the start state back; 'shown' plays
   * it. Omit it entirely for a static pill.
   */
  phase?: 'final' | 'armed' | 'shown';
  /**
   * When set, the pill drops to its OWN LINE (display:block, width fit-content) below 375px. The
   * Grahak OS hero needs this: its headline reads "Reach customers / across <pill>", and the
   * pill's width swings ~146px between "SMS" and "WhatsApp", which re-breaks the line and changes
   * the h1's height on every rotation on a narrow screen. Giving the pill its own line below the
   * threshold holds the line count constant. Omit for heroes that do not need it.
   */
  blockBelow?: number;
}

const RotatingPill: React.FC<RotatingPillProps> = ( { words, phase = 'final', blockBelow } ) => {
  const [ cycleIndex, setCycleIndex ] = useState( 0 );
  const [ paused, setPaused ] = useState( false );

  // Normal foreground browsing rotates indefinitely. A deliberate press of
  // the pill stops until the next press, even after focus moves elsewhere.
  // Hidden tabs and system reduced motion suspend the clock without resetting
  // the user's explicit pause or catching up missed ticks.
  useEffect( () => {
    if ( paused || words.length <= 1 ) return undefined;
    const media = typeof window.matchMedia === 'function' ? window.matchMedia( '(prefers-reduced-motion: reduce)' ) : null;
    const canRotate = () => !media?.matches && document.visibilityState !== 'hidden';
    const clock = createHeroRotationClock(
      ( tick, delay ) => window.setInterval( tick, delay ),
      timer => window.clearInterval( timer ),
      () => {
        if ( canRotate() ) setCycleIndex( index => ( index + 1 ) % words.length );
      },
    );
    const sync = () => clock.sync( canRotate() );
    sync();
    document.addEventListener( 'visibilitychange', sync );
    if ( media?.addEventListener ) media.addEventListener( 'change', sync );
    else media?.addListener?.( sync );
    return () => {
      clock.stop();
      document.removeEventListener( 'visibilitychange', sync );
      if ( media?.removeEventListener ) media.removeEventListener( 'change', sync );
      else media?.removeListener?.( sync );
    };
  }, [ words.length, paused ] );

  const active = words.length ? cycleIndex % words.length : 0;
  const phaseClass = [
    'rp-mark',
    words.length > 1 ? 'is-interactive' : '',
    phase === 'armed' || phase === 'shown' ? 'is-armed' : '',
    phase === 'shown' ? 'is-shown' : '',
    // The narrow-width "drop the pill to its own line" fix is a static rule below, gated on this
    // modifier so no dynamic interpolation lands inside the styled-jsx block (a nested backtick
    // there ends the CSS literal early - the codebase guards against exactly that).
    blockBelow ? 'is-block-narrow' : '',
  ].filter( Boolean ).join( ' ' );

  return (
    <span className={ phaseClass } style={ { background: words[ active ]?.tint } }>
      <i className="rp-mark-dot" style={ { background: words[ active ]?.dot } } aria-hidden="true" />
      <span className="rp-cycle">
        {/* The rotation is visual only: screen readers get the list once; every animated copy is hidden. */}
        <span className="rp-sr-only">{ words.map( w => w.word ).join( ', ' ) }</span>
        { words.map( ( w, i ) => (
          <span
            key={ w.word }
            className={ `rp-cyc-word${i === active ? ' on' : ''}` }
            data-wc-translate="true"
            aria-hidden="true"
          >{ w.word }</span>
        ) ) }
      </span>
      { words.length > 1 && (
        <button
          type="button"
          className="rp-toggle"
          aria-label="Pause headline animation"
          aria-pressed={ paused }
          title={ paused ? 'Resume animation' : 'Pause animation' }
          onClick={ () => setPaused( previous => !previous ) }
        />
      ) }

      <style jsx>{`
        /* THE PILL, SELF-SCOPED (rp-*). Sizes to the headline it sits in: no font-size here, so it
           inherits the host h1's clamp. Values are the heroes' shared ones - the shutter wipe, the
           dot pop and the width glide, with the FINISHED state as the CSS default so a no-JS /
           reduced-motion render shows a complete pill. */
        /* Reserve the maximum intrinsic word width/height, capped by the
           actual headline. A word can wrap without clipping; the surrounding
           page does not shift when a different length becomes active. */
        .rp-mark{
          position:relative;display:inline-flex;align-items:center;gap:.18em;
          box-sizing:border-box;border-radius:9999px;
          padding:.02em .3em .02em .22em;margin-top:.08em;white-space:normal;
          transition:background-color .52s cubic-bezier(.16,1,.3,1);
          max-width:100%;min-width:0;
        }
        /* The existing pill is the hit area. No separate text, icon or row. */
        .rp-mark.is-interactive{min-height:44px;min-width:min(44px,100%)}
        .rp-toggle{position:absolute;inset:0;z-index:2;box-sizing:border-box;width:100%;height:100%;margin:0;padding:0;border:0;border-radius:inherit;background:transparent;cursor:pointer;touch-action:manipulation}
        .rp-toggle:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
        @media(forced-colors:active){.rp-toggle:focus-visible{outline-color:Highlight}}
        /* The white shutter. scaleX(0) (finished) by default, so the tint is never left covered. */
        .rp-mark::before{
          content:'';position:absolute;inset:0;background:#fff;border-radius:9999px;
          transform:scaleX(0);transform-origin:right center;
          transition:transform .78s cubic-bezier(.16,1,.3,1) .18s;z-index:0;
        }
        .rp-mark.is-armed::before{transform:scaleX(1)}
        .rp-mark.is-armed.is-shown::before{transform:scaleX(0)}
        .rp-mark-dot{
          position:relative;z-index:1;display:inline-block;width:.33em;height:.33em;flex:0 0 .33em;
          background:#3da35a;border-radius:50%;margin-inline-end:0;
          transform:scale(1);transition:transform .5s cubic-bezier(.34,1.56,.64,1) .72s;
        }
        .rp-mark.is-armed .rp-mark-dot{transform:scale(0)}
        .rp-mark.is-armed.is-shown .rp-mark-dot{transform:scale(1)}
        /* All words share one grid cell, including the invisible ones.
           Intrinsic sizing follows late fonts and translations without JS
           measurement; short words cannot change the headline's line count. */
        .rp-cycle{
          position:relative;z-index:1;display:grid;grid-template-columns:minmax(0,1fr);
          width:max-content;max-width:100%;min-width:0;height:auto;min-height:1.06em;
          /* Reserve the font's ascender/descender overhang, not just its line box.
             This keeps the settled glyph range inside the animation clip. */
          box-sizing:border-box;padding-block:.10em;line-height:1.1;overflow:hidden;
        }
        .rp-cyc-word{
          grid-area:1/1;position:relative;display:block;min-width:0;align-self:center;
          white-space:normal;overflow-wrap:anywhere;opacity:0;transform:translateY(.42em);
          transition:opacity .42s cubic-bezier(.16,1,.3,1),transform .42s cubic-bezier(.16,1,.3,1);
        }
        .rp-cyc-word.on{opacity:1;transform:translateY(0);position:relative;display:block}
        .rp-cyc-word.on{max-width:100%;white-space:normal;overflow-wrap:anywhere}
        .rp-sr-only{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        @media(prefers-reduced-motion:reduce){
          .rp-toggle{display:none}
          .rp-mark,.rp-mark::before,.rp-mark-dot{transition:none}
          .rp-mark.is-armed::before{transform:scaleX(0)}
          .rp-mark.is-armed .rp-mark-dot{transform:scale(1)}
          .rp-cycle,.rp-cyc-word{transition:none}
        }
        /* Retain the opt-in narrow separate-line behavior for callers. */
        @media(max-width:374px){
          .rp-mark.is-block-narrow{display:flex;width:fit-content}
        }
      `}</style>
    </span>
  );
};

export default RotatingPill;
