import React, { useEffect, useRef, useState } from 'react';

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
 * STATIC PILL: a one-element `words` array never advances (the interval does not start) and the
 * host can simply leave `phase` at its 'final' default, giving a motionless lime pill - the
 * pattern the transactional pages rely on for WCAG 2.2.2.
 */

export interface CycleWord {
  word: string;
  /** Pill background tint for this word. */
  tint: string;
  /** Saturated dot of the same hue. */
  dot: string;
}

export interface RotatingPillProps {
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
  const [ cycleW, setCycleW ] = useState<number | null>( null );
  const wordRefs = useRef<( HTMLSpanElement | null )[]>( [] );

  // THE ROTATION, browser-only and reduced-motion-aware. A one-word list never advances.
  useEffect( () => {
    if ( typeof window.matchMedia === 'function'
      && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) return undefined;
    if ( words.length <= 1 ) return undefined;
    const id = window.setInterval( () => setCycleIndex( i => ( i + 1 ) % words.length ), 2400 );
    return () => window.clearInterval( id );
  }, [ words.length ] );

  // RE-MEASURE ON RESIZE AND FONT-LOAD, not only when the word changes (the clamp(...vw...) size
  // and the late Inter swap both change a word's width). Observe the active WORD, not the pill
  // this sets; guarded for jsdom which implements neither ResizeObserver nor document.fonts.
  useEffect( () => {
    const el = wordRefs.current[ cycleIndex ];
    if ( !el ) return undefined;
    const measure = () => setCycleW( el.offsetWidth );
    measure();
    if ( typeof document !== 'undefined' && ( document as any ).fonts?.ready?.then ) {
      ( document as any ).fonts.ready.then( () => measure() );
    }
    if ( typeof ResizeObserver === 'undefined' ) return undefined;
    const ro = new ResizeObserver( measure );
    ro.observe( el );
    return () => ro.disconnect();
  }, [ cycleIndex ] );

  const active = words.length ? cycleIndex % words.length : 0;
  const phaseClass = [
    'rp-mark',
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
      <span className="rp-cycle" style={ cycleW ? { width: `${cycleW}px` } : undefined }>
        {/* The rotation is visual only: screen readers get the list once; every animated copy is hidden. */}
        <span className="rp-sr-only">{ words.map( w => w.word ).join( ', ' ) }</span>
        { words.map( ( w, i ) => (
          <span
            key={ w.word }
            ref={ el => { wordRefs.current[ i ] = el; } }
            className={ `rp-cyc-word${i === active ? ' on' : ''}` }
            data-wc-translate="true"
            aria-hidden="true"
          >{ w.word }</span>
        ) ) }
      </span>

      <style jsx>{`
        /* THE PILL, SELF-SCOPED (rp-*). Sizes to the headline it sits in: no font-size here, so it
           inherits the host h1's clamp. Values are the heroes' shared ones - the shutter wipe, the
           dot pop and the width glide, with the FINISHED state as the CSS default so a no-JS /
           reduced-motion render shows a complete pill. */
        .rp-mark{
          position:relative;display:inline-block;border-radius:9999px;
          padding:.02em .3em .02em .22em;margin-top:.08em;white-space:nowrap;
          transition:background-color .52s cubic-bezier(.16,1,.3,1);
        }
        /* The white shutter. scaleX(0) (finished) by default, so the tint is never left covered. */
        .rp-mark::before{
          content:'';position:absolute;inset:0;background:#fff;border-radius:9999px;
          transform:scaleX(0);transform-origin:right center;
          transition:transform .78s cubic-bezier(.16,1,.3,1) .18s;z-index:0;
        }
        .rp-mark.is-armed::before{transform:scaleX(1)}
        .rp-mark.is-armed.is-shown::before{transform:scaleX(0)}
        .rp-mark-dot{
          position:relative;z-index:1;display:inline-block;width:.33em;height:.33em;
          background:#3da35a;border-radius:50%;margin-inline-end:.18em;vertical-align:.14em;
          transform:scale(1);transition:transform .5s cubic-bezier(.34,1.56,.64,1) .72s;
        }
        .rp-mark.is-armed .rp-mark-dot{transform:scale(0)}
        .rp-mark.is-armed.is-shown .rp-mark-dot{transform:scale(1)}
        /* Width glides from the measured word; overflow:hidden clips the outgoing word.
           width:max-content is the RESTING width so the first render (cycleW null) is not 0. */
        .rp-cycle{
          width:max-content;position:relative;z-index:1;display:inline-block;
          height:1.06em;line-height:1.06em;vertical-align:baseline;overflow:hidden;
          transition:width .52s cubic-bezier(.16,1,.3,1);will-change:width;
        }
        .rp-cyc-word{
          position:absolute;left:0;top:0;white-space:nowrap;opacity:0;transform:translateY(.42em);
          transition:opacity .42s cubic-bezier(.16,1,.3,1),transform .42s cubic-bezier(.16,1,.3,1);
        }
        /* The ACTIVE word returns to flow (position:static + inline-block) so the box above has a
           real intrinsic width; the inactive words stay absolute and stacked. */
        .rp-cyc-word.on{opacity:1;transform:translateY(0);position:static;display:inline-block}
        .rp-sr-only{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        @media(prefers-reduced-motion:reduce){
          .rp-mark::before,.rp-mark-dot{transition:none}
          .rp-mark.is-armed::before{transform:scaleX(0)}
          .rp-mark.is-armed .rp-mark-dot{transform:scale(1)}
          .rp-cycle,.rp-cyc-word{transition:none}
        }
        /* NARROW-WIDTH FIX, opt-in via blockBelow (adds .is-block-narrow). Below 375px the pill
           drops to its own line so a width swing between words cannot re-break the headline and
           change its height on every rotation. Static rule - no interpolation inside this
           styled-jsx block, because a backtick here would end the CSS literal early. The Grahak OS
           hero is the one caller that needs it. */
        @media(max-width:374px){
          .rp-mark.is-block-narrow{display:block;width:fit-content}
        }
      `}</style>
    </span>
  );
};

export default RotatingPill;
