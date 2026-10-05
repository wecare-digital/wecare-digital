import React, { useEffect, useRef, useState } from 'react';

/**
 * Animated workflow terminal, from the owner's HTML mock, restyled onto the site.
 *
 * SELF-STYLING, like BrandBadge and RotatingHero: styled-jsx cannot scope a composite
 * component from its parent, so this owns every rule it needs and the consumer owns
 * nothing but placement.
 *
 * COLOURS ARE ALL EXISTING VALUES. The mock shipped its own palette - #17191c panel,
 * #659df5 blue, #57c785 green, #dab25f yellow, #a294ff purple, #d98787 red. None of
 * those are in this site's palette, and the design contract already records that
 * inventing in-between values is how #f2fbf6, #fbfff0 and the whole #000 slate ramp
 * got here and had to be retired. So the mapping is:
 *
 *   panel        #000                     both existing code panels are #000
 *   panel edge   1.5px rgba(255,255,255,.92)  the documented editor-pane stroke
 *   base text    #fff
 *   muted        rgba(255,255,255,.54)    the value .pp-tab already uses idle
 *   accent       #d1f470                  lime, our own surface - the owner's ask
 *   warning      #f0a818                  the existing amber dot
 *   removed      #dc2626                  the existing red dot
 *   mono         'SF Mono',Monaco,Consolas,monospace   as .code-body
 *
 * That loses the mock's syntax rainbow on purpose: one accent doing the work reads as
 * this site, five borrowed hues read as a different product embedded in it.
 *
 * THE STREAM IS aria-hidden. It is illustrative, so a screen reader gets one static
 * summary instead of a stream of appearing nodes.
 *
 * IT PLAYS ON LOAD AND LOOPS UNTIL STOPPED, on owner instruction. There is no scroll
 * gate: it used to wait for a one-shot IntersectionObserver at 25% visibility, which
 * meant "does it play?" depended on how the panel happened to enter the viewport. The
 * only condition left is a reader pressing Pause. The background-tab objection that the
 * gate was standing in for is answered directly instead, by `document.hidden` - see the
 * visibility effect - which is both narrower and actually correct: an on-screen panel
 * scrolled past is still on screen, a hidden tab never is.
 */

type Result = { label: string; kind?: 'ok' | 'warn' };
type Lane = { name: string; detail: string };

interface Step {
  /** The service that did the work, shown as the lane label. */
  service: string;
  name: string;
  description: string;
  time: string;
  /** Shared infrastructure this step ran on, rendered as a code comment. */
  infra?: string;
  command?: React.ReactNode;
  results?: Result[];
  /** Concurrent services. Rendered as parallel lanes, not a sequence. */
  lanes?: Lane[];
  checks?: string[];
  complete?: boolean;
}

/**
 * WHAT THIS PANEL SAYS ABOUT THE COMPANY, which is the whole reason it was rewritten.
 *
 * It used to run an agent loop: Plan, Read configuration, Call tool, Inspect result,
 * "confidence 0.71", Retry, Optimize, Run checks. Every one of those beats is the visual
 * grammar of an autonomous-agent demo, and a visitor reading it would reasonably conclude
 * this is an agentic AI product. The owner's position is the opposite: WECARE.DIGITAL runs
 * many services on one shared platform, and the AI parts are a feature of a few of them,
 * not the thing being sold.
 *
 * So the stream now shows what the backend actually does on a single request - gateway,
 * auth, contacts, four messaging workers in parallel, commerce, billing, the queue
 * absorbing a provider failure, and the health rollup. These are the real service
 * families in this repo (amplify/functions/{core,messaging,ecommerce,operations}), not
 * invented ones.
 *
 * THE INFRA IS NAMED IN COMMENT LINES. Each step carries a "#" line listing the shared
 * components it used, which is what makes the point the headline makes in words: the
 * services are different, the foundation underneath them is the same one. The parallel
 * lanes in the messaging step exist to show concurrency directly - a vertical list would
 * have read as four more sequential steps, which is precisely the wrong impression.
 *
 * Nothing here claims a benchmark. The timings are illustrative and the panel is
 * aria-hidden with a static summary, so no assistive technology is told these are
 * measurements.
 */
const STEPS: Step[] = [
  {
    service: 'gateway', name: 'Request accepted', time: '12ms',
    description: 'One HTTPS request arrives and is routed to the handler for this account.',
    infra: 'your request is accepted securely',
  },
  {
    service: 'auth', name: 'Account resolved', time: '31ms',
    description: 'The caller is verified and scoped, so every later step is limited to their data.',
    infra: 'your account is verified and isolated',
    results: [ { label: 'verified', kind: 'ok' }, { label: 'scope: account_2841' } ],
  },
  {
    service: 'contacts', name: 'Customer looked up', time: '18ms',
    description: 'A single-key read returns the customer and the channels they agreed to.',
    infra: 'your record is read in one step',
    command: <><span className="wt-sh">$</span><span className="wt-fn">contacts.get</span>(<span className="wt-str">&quot;cust_2841&quot;</span>) <span className="wt-cm">— 1 read unit</span></>,
  },
  {
    service: 'messaging', name: 'Four services pick it up at once', time: '46ms',
    description: 'Independent workers run in parallel. None of them waits for another to finish.',
    infra: 'four channels are queued, each independent',
    lanes: [
      { name: 'whatsapp', detail: 'template delivered' },
      { name: 'sms', detail: 'queued with operator' },
      { name: 'email', detail: 'sent' },
      { name: 'voice', detail: 'callback scheduled' },
    ],
  },
  {
    service: 'commerce', name: 'Order and catalog updated', time: '54ms',
    description: 'Stock and order state change together, so the two cannot disagree.',
    infra: 'the order and stock update together',
    results: [ { label: 'order confirmed', kind: 'ok' }, { label: 'stock −1' } ],
  },
  {
    service: 'billing', name: 'Usage metered', time: '9ms',
    description: 'What was actually sent is recorded against this account for the period.',
    infra: 'usage is metered from the same stream',
  },
  {
    service: 'queue', name: 'A provider failed, nobody noticed', time: '1.2s',
    description: 'One carrier returned an error. The message went back on the queue and left on the next attempt.',
    infra: 'a failed send retries and is watched',
    results: [ { label: 'attempt 2 of 5', kind: 'warn' }, { label: 'delivered', kind: 'ok' }, { label: 'dead-letter empty', kind: 'ok' } ],
  },
  {
    service: 'platform', name: 'All services healthy', time: '2.1s', complete: true,
    description: 'Every service above reported success, on the same logs, metrics and traces.',
    infra: 'every service reports to one place',
    checks: [ 'eight services, one deployment', 'one identity, one audit trail', 'one bill' ],
  },
];

// Per-step dwell: richer steps hold longer so there is time to read them. Keyed off what
// the step contains rather than its index, so reordering STEPS does not silently retime
// the sequence.
const dwell = ( step: Step ): number => {
  if ( step.lanes ) return 1650;
  if ( step.complete ) return 1600;
  if ( step.checks ) return 1450;
  if ( step.command ) return 1400;
  return 1050;
};

/**
 * Is this document in a tab nobody can see?
 *
 * visibilityState === 'hidden', NOT document.hidden, and the difference is not pedantry.
 * `document.hidden` is true for ANY state that is not 'visible', which includes 'prerender'.
 * jsdom reports exactly that - hidden true, visibilityState 'prerender' - so gating on
 * `document.hidden` silently froze the whole sequence under test, and it would do the same to
 * a prerendered page in a browser that still exposes that state. A prerender is a document
 * heading for the screen, not one that left it. Only 'hidden' means the reader is elsewhere,
 * and that is the only case worth stopping a timer for.
 */
const isHidden = (): boolean =>
  typeof document !== 'undefined' && document.visibilityState === 'hidden';

const WorkflowTerminal: React.FC = () => {
  /* THE INITIAL STATE IS THE FINISHED RUN, NOT AN EMPTY BOX - which is the .is-armed inversion
   * the home page already uses for its hero and its closing band, applied here at last.
   *
   * These were 0 / -1 / false, so the static export rendered ZERO rows. Measured on the built
   * HTML: `grep -c "Request accepted" out/index.html` returned 0, and with JavaScript disabled
   * the largest element on the home page was a 650px black rectangle holding one line of text
   * and a footer reading "running 0 / 8 services". Every word of the eight steps existed only
   * after hydration, so a no-JS reader, a WebView with scripting off, and anything reading the
   * HTML rather than running it all got an empty panel - on the same site that just started
   * publishing llms.txt and an /mcp endpoint for exactly those readers.
   *
   * Shipping the COMPLETE state fixes it with no new markup: eight rows, all settled, footer
   * reading "complete". It is also the most meaningful single frame the panel has, it is
   * byte-identical to what a reduced-motion visitor already gets, and it removes the last place
   * the panel was ever nearly empty - the first-load state, which the loop was already fixed
   * for but the initial render was not.
   *
   * Hydration is safe because these are plain initial values, identical on both sides; nothing
   * here reads a browser global. The animation then starts from this state rather than replacing
   * it - see `resumeRef`, which begins at STEPS.length so the first thing the stepper does is
   * serve the end-of-pass hold and loop round, exactly as it does on every later cycle. So there
   * is no flash: the panel a reader sees before JavaScript runs is the panel it keeps.
   */
  const [ shown, setShown ] = useState( STEPS.length );
  const [ settled, setSettled ] = useState( STEPS.length );
  const [ done, setDone ] = useState( true );
  /* The loop's pause control and its restart counter. `paused` gates the restart at the end of
   * a pass AND is what makes the continuous animation WCAG 2.2.2 conformant; `cycle` bumping is
   * what re-enters the stepping effect for another pass. */
  const [ paused, setPaused ] = useState( false );
  const [ cycle, setCycle ] = useState( 0 );
  const [ run, setRun ] = useState( false );
  /* Tab-level visibility, the one thing other than Pause that stops the stepper. It is not a
   * reader-facing state: nobody is looking at a hidden tab, so stopping there is invisible,
   * and `resumeRef` means coming back continues rather than restarts. */
  const [ hidden, setHidden ] = useState( false );
  const rootRef = useRef<HTMLDivElement | null>( null );
  const streamRef = useRef<HTMLDivElement | null>( null );

  /* START PLAYING, FULL STOP. This effect used to decide WHETHER to play: a one-shot
   * IntersectionObserver at 25% threshold held `run` false until the panel was scrolled into
   * view. The owner's instruction is that the panel plays in a loop on its own, and a
   * visibility gate is a condition on that - so the observer is gone and `run` is set
   * unconditionally.
   *
   * REDUCED MOTION NOW STARTS PAUSED RATHER THAN DEAD. It still lands on the finished state,
   * because the sequence is the decoration and the content is not - but it also sets `paused`
   * and still sets `run`, which changes two things that were both defects. The control reads
   * "Play" instead of offering to pause something that was never moving, and pressing it
   * actually starts the loop. Before, `run` stayed false forever on that path, so the button
   * was inert: a reader who has reduced motion set at the OS level but wants to watch this one
   * illustration had no way to.
   *
   * EVERY STATE CHANGE HERE IS SCHEDULED rather than called in the effect body. Writing
   * setShown/setRun straight into the body is the react-hooks/set-state-in-effect error - the
   * repo already carries 116 of those and this file is not adding more. It cannot be hoisted
   * into a lazy useState initialiser either, because the branch reads browser-only globals
   * (matchMedia, visibilityState) that are undefined during the static export and would hydrate
   * to a different value than they render to. A timeout of 0 resolves both: the decision happens
   * after commit, on the client, one frame later than paint, which is invisible for an element
   * that starts empty anyway.
   */
  useEffect( () => {
    let cancelled = false;

    const id = window.setTimeout( () => {
      if ( cancelled ) return;

      setHidden( isHidden() );

      const reduce = typeof window.matchMedia === 'function'
        && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
      // The finished state is now the INITIAL state, so this branch no longer has to build it -
      // it only has to stop the stepper from leaving it. `paused` rather than a missing `run`,
      // so the control still means something.
      if ( reduce ) setPaused( true );
      setRun( true );
    }, 0 );

    return () => { cancelled = true; window.clearTimeout( id ); };
  }, [] );

  /* THE BACKGROUND-TAB GUARD, which is what the removed scroll gate was really for. An
   * infinite loop on a homepage should not keep stepping in a tab nobody is looking at; that
   * objection is legitimate and predates this change. Tab visibility answers it exactly, where
   * "scrolled 25% into view" only answered it by accident. Pressing nothing and coming back to
   * the tab resumes mid-pass, because the stepper restarts from `resumeRef`. */
  useEffect( () => {
    const onVisibility = () => setHidden( isHidden() );
    document.addEventListener( 'visibilitychange', onVisibility );
    return () => document.removeEventListener( 'visibilitychange', onVisibility );
  }, [] );

  // The sequence. One chained timeout rather than an interval, so a slow frame cannot
  // stack two steps on top of each other.
  //
  // IT LOOPS CONTINUOUSLY, WITH A PAUSE CONTROL. It played once and held before that, and it
  // looped before THAT - so this is the third state of this decision and the history matters,
  // because the original loop had two real defects and neither is allowed back.
  //
  // The original reset to `shown: 0` and restarted. Measured restart-edge to restart-edge, one
  // cycle was 15.8s - 12.6s streaming and 3.2s holding.
  //
  //   1. WCAG 2.2.2. Content that moves automatically for more than five seconds must be
  //      pausable, stoppable or hideable. The original offered none of the three. Playing once
  //      was the conformant answer that needed no new control, which is why it was preferred
  //      at the time over adding a button.
  //   2. THE PANEL EMPTIED ITSELF. The reset dropped it back to one 26px line inside a 551px
  //      box - 95% empty - every 15.8s. So the largest element on the home page spent part of
  //      every cycle showing nothing, and anyone arriving mid-reset met a black rectangle.
  //
  // Owner asked for continuous play. BOTH DEFECTS ARE FIXED RATHER THAN RE-ACCEPTED:
  //   1. is answered by .wt-play, a real pause control rendered outside the aria-hidden window
  //      so it is exposed to assistive tech rather than focusable-but-invisible.
  //   2. is answered by never rewinding `shown`. Only `settled` rewinds, so all eight rows stay
  //      mounted for the whole cycle and the panel is never empty at any moment.
  //
  // The closing band's reveal stays one-shot for its own stated reason - it did not want to
  // compete with the continuously moving things above it, and this panel is one of those again.
  //
  // THE FIRST STEP LANDS IMMEDIATELY. There was a 600ms delay before step 0, on top of the
  // observer gate, so the panel held its empty state for a measurable beat after coming into
  // view. Nothing needed that delay - the entrance animation on each step is what gives the
  // arrival its softness, and it still runs.
  /*
   * WHERE THE NEXT PASS RESUMES FROM. `paused` is in this effect's dependency list, so toggling
   * it tears the effect down and sets it up again - and the first version of the pause called
   * step(0) on the way back, which meant pressing Pause RESTARTED the sequence instead of
   * stopping it. replaycheck caught it: the settle frontier read 2,0,1,3 while paused.
   *
   * A ref rather than state, because writing it must not itself re-run the effect that reads it.
   */
  /* STEPS.length, NOT 0, and that is what makes the static complete state seamless. The stepper
   * resumes from here, so its first act is to enter the end-of-pass branch: hold the finished
   * panel for 3.2s, then rewind and replay, then loop. A visitor therefore reads a completed run
   * first and watches it replay - rather than seeing eight settled rows blink back to running
   * one frame after hydration, which is what starting at 0 would have produced. */
  const resumeRef = useRef( STEPS.length );

  useEffect( () => {
    /* PAUSED MEANS NO STEPPER AT ALL. Returning before anything is scheduled is what makes the
     * pause real - a paused machine that still holds a pending timeout is just a slower machine.
     * The CSS halts the dot pulse separately; both are needed for WCAG 2.2.2. */
    if ( !run || paused || hidden ) return undefined;
    let cancelled = false;
    let timer = 0;

    const step = ( index: number ) => {
      if ( cancelled ) return;
      // Remembered every step, so an unpause resumes here instead of rewinding to the top.
      resumeRef.current = index;
      if ( index >= STEPS.length ) {
        setDone( true );
        /*
         * IT LOOPS AGAIN, ON OWNER INSTRUCTION - BUT NOT THE LOOP THAT WAS REMOVED.
         *
         * The old loop reset `shown` to 0, and that is the defect recorded above: the panel
         * dropped to a single 26px line inside a 551px box, 95% empty, every 15.8s, so the
         * largest element on the home page periodically showed nothing and anyone arriving
         * mid-reset met a black rectangle.
         *
         * THIS RESTART LEAVES `shown` AT STEPS.length AND ONLY REWINDS `settled`. All eight
         * rows stay mounted and on screen for the entire cycle; what replays is the
         * running-to-done pass travelling down them. The panel is never empty at any point,
         * which is the whole objection answered rather than accepted.
         *
         * What a reader sees at the restart edge is the stack going live at once and then
         * settling row by row - a heartbeat rather than a rebuild. Stated because eight dots
         * pulsing for one beat is a real visual event and someone reading this file should
         * know it is intended, not a race.
         *
         * WCAG 2.2.2 IS SATISFIED BY THE CONTROL, NOT BY LUCK. Content that moves
         * automatically for more than five seconds must be pausable, stoppable or hideable,
         * and this cycle is far longer than five seconds. That is why the pause button exists
         * and why it is rendered OUTSIDE the aria-hidden window subtree - a focusable control
         * inside aria-hidden is reachable by keyboard while absent from the accessibility
         * tree, which trades one failure for a worse one. `paused` also short-circuits here,
         * so pausing stops the machine rather than just hiding its effect.
         *
         * Reduced motion does not reach this line unless it was asked to. That path starts on
         * the finished state with `paused` set, so no loop runs - but `run` IS set now, so a
         * reader who presses Play gets one. That is the preference respected by default and
         * overridable on request, rather than a control that silently does nothing.
         */
        timer = window.setTimeout( () => {
          if ( cancelled ) return;
          setDone( false );
          setSettled( -1 );
          resumeRef.current = 0;
          /* A new pass gets the view back - see the note on followRef.
           * `autoTop` is deliberately NOT reset here. It was, as belt-and-braces against a stale
           * expected position swallowing the reader's first scroll of the next pass - but writing
           * it in this effect is what made react-hooks/immutability reject the write in the
           * follow effect below, and the guard was never load-bearing: every auto-scroll is
           * followed by a scroll event that consumes the value, and the follow effect overwrites
           * it before each scroll regardless. */
          followRef.current = true;
          setCycle( c => c + 1 );
        }, 3200 );
        return;
      }
      // Only the first pass reveals rows. Every later pass finds all eight already mounted,
      // which is what keeps the panel from emptying itself.
      setShown( prev => ( prev > index + 1 ? prev : index + 1 ) );
      timer = window.setTimeout( () => {
        if ( cancelled ) return;
        setSettled( index );
        timer = window.setTimeout( () => step( index + 1 ), 250 );
      }, dwell( STEPS[ index ] ) );
    };

    step( resumeRef.current );
    return () => { cancelled = true; window.clearTimeout( timer ); };
  }, [ run, paused, hidden, cycle ] );

  /* PLAY HAS TO PLAY, and in two states it did not.
   *
   *   1. Pause pressed during the 3.2s "complete" hold left `resumeRef` at STEPS.length, so
   *      Play re-entered the end branch: the panel then sat completely still for another 3.2s
   *      before anything moved. Pressing Play and watching nothing happen for three seconds is
   *      indistinguishable from a broken button.
   *   2. A reduced-motion visitor starts on the finished state with every row settled, so
   *      there was no frontier left to travel and the first thing Play could do was wait out a
   *      dwell before rewinding.
   *
   * One fix for both: if the stream is already at its end, rewind the frontier on the way in so
   * Play starts a pass. Pause is untouched - it is a stop, and it must not rewind anything, or
   * it becomes the restart bug recorded above.
   */
  const togglePlay = () => {
    if ( paused && ( done || resumeRef.current >= STEPS.length || settled >= STEPS.length - 1 ) ) {
      resumeRef.current = 0;
      setDone( false );
      setSettled( -1 );
    }
    setPaused( p => !p );
  };

  /* WHO OWNS THE PANEL'S SCROLL POSITION.
   *
   * `followRef` is on while the animation may move the view, and off once the READER has
   * scrolled the panel themselves. A scroll event carries no flag saying who caused it, so the
   * two have to be told apart some other way.
   *
   * BY POSITION, NOT BY TIME, and that distinction cost a measured bug. The first version of
   * this recorded the TIMESTAMP of each scroll we caused and ignored scroll events within 150ms
   * of it. Traced in Chromium and Firefox: a step's auto-scroll landed at -6ms, the reader's
   * wheel fired at 0 and its scroll event arrived at +62ms - 68ms after our own, inside the
   * window - so the reader's scroll was classified as ours and the panel kept dragging the view
   * away from them. Steps are 1050-1650ms apart, so roughly one scroll in ten hit that window,
   * and because the cycle is deterministic a scroll at a fixed offset hit it EVERY time, which
   * is how both engines failed identically.
   *
   * `autoTop` instead holds the exact scrollTop we are about to write. A scroll event that lands
   * on that value is ours and is consumed; anything else is the reader's, whatever the timing.
   * 2px of tolerance for fractional scroll offsets on fractional device pixel ratios - a phone
   * at dpr 2.75 does not round to integers.
   */
  const followRef = useRef( true );
  const autoTop = useRef( -1 );

  /* FOLLOW THE MOVING EDGE, NOT THE BOTTOM - and this is the fix that makes the loop visible
   * rather than merely running.
   *
   * This effect used to do `box.scrollTop = box.scrollHeight` - slam to the bottom. That was
   * right for a stream that only ever grows, which is what pass one is. It is WRONG for a loop.
   * Measured, with the panel scrolled to the middle of the viewport: on pass two the box sat at
   * scrollTop 799/799 at 1280 and 1439/1439 at 390, so the visible rows were 4-7 and 6-7
   * respectively, while the running-to-done frontier travelled rows 0 through 7 above the
   * visible edge. The moving edge was off screen in 6 of 7 samples, about 11 of every 15.8
   * seconds. The animation was playing perfectly and a reader could not see it: the panel read
   * as a frozen screenshot of its own last two rows.
   *
   * So the target is the FRONTIER row - index settled+1, the one that is currently running -
   * and the box scrolls only as far as it takes to bring that row inside itself. On pass one
   * the frontier is always the newest row, so this behaves exactly like following the tail. On
   * every later pass it tracks the replay from the top, which is the thing there is to watch.
   * At a restart `settled` is -1, so the frontier is row 0 and the panel rewinds to the top by
   * the same arithmetic rather than by a special case.
   *
   * THE BOX, NEVER THE PAGE. scrollTop arithmetic on the box, not scrollIntoView, which walks
   * up every scrollable ancestor and would drag the whole document to the panel.
   *
   * WHY NOT GROW THE PANEL SO NOTHING SCROLLS, which was the earlier alternative. Measured:
   * fitting the content needs 1447px at 1280 and 1997px at 390, against 650 and 560 today. On
   * a phone that is 2.4 screens of black terminal, and the page goes from 2498px to 3935px.
   *
   * THE READER STILL WINS WHILE THEY ARE READING. Their own scroll clears `followRef`, so the
   * rest of that pass leaves the view where they put it - about 12.6 seconds undisturbed, which
   * is what the original "stop fighting a reader who scrolls back" note was protecting and it
   * is still protected. Following resumes at the next restart, stated plainly because it IS a
   * yank: the cost of never resuming is a reader who scrolls once and then watches a permanently
   * still panel for as long as the tab is open, which is the defect above with extra steps. It
   * lands on the restart edge, where the whole stack already pulses, so it coincides with a
   * visual event that is there anyway instead of introducing a new one.
   */
  useEffect( () => {
    const box = streamRef.current?.parentElement;
    const stream = streamRef.current;
    if ( !box || !stream || !followRef.current ) return;
    const rows = stream.children;
    if ( !rows.length ) return;
    /* NOTHING IS RUNNING, SO THERE IS NO EDGE TO FOLLOW - leave the view where the reader has it.
     * This guard is what keeps the new static complete state readable from the top: on mount
     * `settled` is STEPS.length, and without it the clamp below would resolve to the LAST row and
     * scroll a freshly loaded panel straight to its bottom before anything had moved. It also
     * covers the end of every pass, where the final row settles and the frontier walks off the
     * end; that row was already brought into view one step earlier. */
    if ( settled >= rows.length - 1 ) return;
    const row = rows[ Math.max( settled + 1, 0 ) ] as HTMLElement;
    const bb = box.getBoundingClientRect();
    const rb = row.getBoundingClientRect();
    const pad = 16;
    let delta = 0;
    if ( rb.bottom > bb.bottom - pad ) delta = rb.bottom - ( bb.bottom - pad );
    else if ( rb.top < bb.top + pad ) delta = rb.top - ( bb.top + pad );
    if ( !delta ) return;
    /* AN ABSOLUTE TARGET, CLAMPED HERE RATHER THAN BY THE BROWSER. `scrollTop += delta` past
     * either end is silently clamped, so the value that lands is not the value asked for - and
     * the listener above, which recognises our own scroll by its position, would then read it
     * as the reader's and hand over control we never gave away. */
    const max = box.scrollHeight - box.clientHeight;
    const target = Math.max( 0, Math.min( max, box.scrollTop + delta ) );
    if ( Math.abs( target - box.scrollTop ) < 1 ) return;
    autoTop.current = target;
    box.scrollTop = target;
  }, [ shown, settled ] );

  /* THE HAND-OVER LISTENER, AND IT IS DECLARED AFTER THE EFFECT ABOVE ON PURPOSE.
   * react-hooks/immutability rejects writing a ref that an EARLIER effect already read, so with
   * this listener first the `autoTop.current = target` above was a lint error. Ordering it after
   * removes the error without a suppression comment and costs nothing: both effects mount on the
   * same commit, and on that first commit `shown` is 0, so the effect above finds no rows and
   * returns before scrolling anything. There is no scroll for this listener to miss. */
  useEffect( () => {
    const box = streamRef.current?.parentElement;
    if ( !box ) return undefined;
    const onScroll = () => {
      if ( autoTop.current >= 0 && Math.abs( box.scrollTop - autoTop.current ) <= 2 ) {
        autoTop.current = -1;
        return;
      }
      followRef.current = false;
    };
    box.addEventListener( 'scroll', onScroll, { passive: true } );
    return () => box.removeEventListener( 'scroll', onScroll );
  }, [] );

  const visible = STEPS.slice( 0, shown );

  return (
    <section
      className={ `wt-wrap ${paused ? 'is-paused' : ''}`.trim() }
      ref={ rootRef }
      aria-label="How a workflow runs"
    >
      {/* One static sentence for assistive tech. The stream below is aria-hidden: a
          screen reader should not receive eight nodes appearing on timers. */}
      <p className="wt-sr">
        An illustration of one customer request moving through our services: the request is
        accepted, the account is verified, the customer record is read, four channels deliver
        at once, the order and stock are written together, usage is metered, a failed send is
        retried and watched, and all eight services report healthy — every one of them on the
        same shared foundation.
      </p>

      {/* dir="ltr" LOCKS THE TERMINAL, and it is a correctness fix rather than a preference.
          This panel draws literal machine output - a shell prompt, "platform / production",
          $contacts.get("cust_2841"), "# dynamodb · single-table". None of that is prose and
          none of it is left-to-right by convention: it is left-to-right by SYNTAX. With the
          document mirrored for an Arabic reader the flex rows inside reversed, so the window
          lights moved to the right, the prompt reversed, and the punctuation in the call
          reordered - a reader who knows the API would see code that no longer parses.
          Found by measuring mirror symmetry, not by looking: comparing each element's
          distance from the inline-start edge in ltr against rtl, this subtree was the largest
          asymmetry on the home page at 726px.
          It pairs with the aria-hidden already here. Both say the same thing about this
          panel - it is a picture of a machine, not text - so it is exempt from translation
          and from mirroring for one reason. */}
      {/* THE PAUSE CONTROL SITS OUTSIDE .wt-window ON PURPOSE, and the purpose is not layout.
          The window carries aria-hidden="true" because a screen reader should not receive eight
          nodes appearing on timers - the static .wt-sr paragraph above is what it gets instead.
          A <button> placed inside that subtree would still be in the tab order while absent
          from the accessibility tree: reachable by keyboard, announced as nothing. So the
          control is a sibling and is positioned over the title bar with CSS.

          IT EXISTS BECAUSE THE LOOP EXISTS. WCAG 2.2.2 requires content that moves
          automatically for more than five seconds to be pausable, stoppable or hideable, and
          one cycle here runs about 15.8s. This is the pause. It is the reason the panel is
          allowed to animate continuously at all, not a convenience bolted on afterwards.

          The label is real text rather than an icon glyph, and that is deliberate after the
          tick: this sandbox has 82 fonts and none with symbol coverage, so a play triangle or
          pause bars written as U+25B6 / U+23F8 would render as tofu somewhere. Two CSS-drawn
          bars and a CSS-drawn triangle cannot fall back to a missing glyph. */}
      {/* RENDERED ONLY ONCE THERE IS SOMETHING TO CONTROL. `run` is false during the static
          export and on the first client render, and becomes true one tick later - so the HTML
          ships without this button and a reader with JavaScript disabled is not offered a Pause
          control for an animation that cannot start. It used to ship unconditionally, which left
          a no-JS visitor a button labelled "Pause" sitting over a panel that was never going to
          move. Hydration-safe because the condition is identical on both sides of the boundary,
          and no layout shifts when it arrives: .wt-bar already reserves 108px of right padding
          for its footprint. */}
      { run && (
        <button
          type="button"
          className={ `wt-play ${paused ? 'is-paused' : ''}`.trim() }
          onClick={ togglePlay }
          aria-pressed={ paused }
        >
          <span className="wt-play-mark" aria-hidden="true" />
          { paused ? 'Play' : 'Pause' }
          <span className="wt-sr-only"> the illustration of a customer request</span>
        </button>
      ) }

      <div className="wt-window" aria-hidden="true" dir="ltr">
        <div className="wt-bar">
          {/* Class names carry the POSITION, not the colour. They were wt-red / wt-amber /
              wt-lime and each one outlived the colour it named at least once - see the rule
              block. A name that lies about its value is worse than a generic one. */}
          <span className="wt-light wt-light-1" />
          <span className="wt-light wt-light-2" />
          <span className="wt-light wt-light-3" />
          <span className="wt-bar-title">platform / production</span>
          <span className="wt-bar-state"><i className="wt-state-dot" />8 services · 1 foundation</span>
        </div>

        <div className="wt-space">
          <div className="wt-request"><span className="wt-caret">›</span><span>One customer places an order. Watch what runs behind it.</span></div>

          <div ref={ streamRef }>
            { visible.map( ( step, i ) => {
              const state = i <= settled ? 'is-done' : 'is-running';
              const last = i === STEPS.length - 1;
              return (
                <div key={ step.name } className={ `wt-step ${state} ${last ? 'is-last' : ''}`.trim() }>
                  <span className="wt-dot" />
                  <div className="wt-head">
                    <span className="wt-svc">{ step.service }</span>
                    <span className={ `wt-name ${step.complete ? 'is-complete' : ''}`.trim() }>
                      { step.complete && <span className="wt-tick">✓ </span> }
                      { step.name }
                    </span>
                    <span className="wt-time">{ step.time }</span>
                  </div>
                  <p className="wt-desc">{ step.description }</p>

                  { step.command && <div className="wt-cmd">{ step.command }</div> }

                  { /* The shared foundation, written the way it would appear in code. This
                       is the line that carries the actual claim: different services,
                       same infrastructure underneath. */ }
                  { step.infra && <div className="wt-infra"># { step.infra }</div> }

                  { step.results && (
                    <div className="wt-results">
                      { step.results.map( r => (
                        <span key={ r.label } className={ `wt-chip ${r.kind ? 'is-' + r.kind : ''}`.trim() }>{ r.label }</span>
                      ) ) }
                    </div>
                  ) }

                  { /* PARALLEL LANES, side by side on purpose. Stacked vertically these
                       four would read as four more sequential steps, which is the exact
                       opposite of the point - they run at the same time. */ }
                  { step.lanes && (
                    <div className="wt-lanes">
                      { step.lanes.map( lane => (
                        <div key={ lane.name } className="wt-lane">
                          <span className="wt-lane-bar" />
                          <span className="wt-lane-name">{ lane.name }</span>
                          <span className="wt-lane-detail">{ lane.detail }</span>
                        </div>
                      ) ) }
                    </div>
                  ) }

                  { step.checks && (
                    <div className="wt-checks">
                      { step.checks.map( c => (
                        <div key={ c } className="wt-check"><span className="wt-check-tick">✓</span>{ c }</div>
                      ) ) }
                    </div>
                  ) }
                </div>
              );
            } ) }
          </div>
        </div>

        {/* OUTSIDE .wt-space, deliberately. In the original mock this footer sits
            inside the scrolling workspace as position:absolute;bottom:0 - and an
            absolutely positioned element in a scroll container anchors to the bottom of
            the SCROLLED CONTENT, not to the visible box. So once the stream grew past
            the panel height the status bar rendered in the middle of the list, on top
            of the steps. It only reproduces after enough rows have streamed in, which
            is why it survived in the mock and why a screenshot caught it here rather
            than an assertion.
            As a flex sibling of the scroll area it is pinned to the window for free,
            and the gradient becomes unnecessary - a solid panel-coloured bar with a
            hairline above it is what actually separates the two. */}
        <div className="wt-foot">
          <span className="wt-foot-left"><i className="wt-foot-dot" />{ done ? 'complete' : 'running' }</span>
          <span className="wt-foot-right">{ done ? '8 services · 1 retry absorbed · 1 platform' : `${shown} / ${STEPS.length} services` }</span>
        </div>
      </div>

      <style jsx>{`
        /* position:relative so .wt-play can be placed over the title bar while living OUTSIDE
           the aria-hidden window in the DOM - see the note on the button. */
        .wt-wrap{width:100%;position:relative}

        /* THE PAUSE CONTROL. Sits on the title bar, which is #3b271a, so the resting state is
           a translucent white chip on brown rather than a hue - the bar already carries three
           coloured lights and a fourth colour there would read as a fifth status signal.
           Measured: #f2efe9 on #3b271a is 9.41:1, and on the lime hover fill 8.87:1, both well
           clear of 4.5:1 for 12px text. */
        .wt-play{
          position:absolute;top:0;right:0;z-index:3;height:47px;
          display:inline-flex;align-items:center;gap:7px;
          padding:0 15px;margin:0;border:0;background:transparent;
          font:inherit;font-size:12px;letter-spacing:.02em;color:#f2efe9;
          cursor:pointer;
          border-top-right-radius:14px;
          transition:background .2s cubic-bezier(.33,0,.24,1),color .2s cubic-bezier(.33,0,.24,1);
        }
        .wt-play:hover,.wt-play:focus-visible{background:rgba(209,244,112,.16);color:#fff}
        /* A real focus ring. The bar is dark, so the lime the rest of the site uses for focus
           reads clearly against it. */
        .wt-play:focus-visible{outline:2px solid #d1f470;outline-offset:-2px}
        /* CSS-DRAWN MARKS, NOT GLYPHS. U+23F8 and U+25B6 have no coverage in several of the
           fonts this site ships and would render as tofu - the same trap the tick hit in the
           review mock. Two bars for pause; a triangle, via borders, for play. */
        .wt-play-mark{display:inline-block;width:9px;height:10px;flex:0 0 auto;position:relative}
        .wt-play-mark::before,.wt-play-mark::after{
          content:'';position:absolute;top:0;width:3px;height:10px;background:currentColor
        }
        .wt-play-mark::before{left:0}
        .wt-play-mark::after{right:0}
        .wt-play.is-paused .wt-play-mark::after{display:none}
        .wt-play.is-paused .wt-play-mark::before{
          left:1px;width:0;height:0;background:transparent;
          border-top:5px solid transparent;border-bottom:5px solid transparent;
          border-left:8px solid currentColor
        }
        /* PAUSE MUST STOP THE MOTION, not just the timers. The stepping effect stops scheduling
           when paused, but .wt-pulse is a CSS animation with infinite iteration on whichever row
           is running - motion that would carry on indefinitely after a reader pressed pause,
           which is exactly what 2.2.2 forbids. Halting it here is what makes the control honest. */
        .wt-wrap.is-paused .wt-step.is-running .wt-dot{animation:none}
        .wt-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
        /* Same clip as .wt-sr, but for text INSIDE a visible control: the button needs to read
           as "Pause the illustration of a customer request" to a screen reader while showing
           only "Pause", because "Pause" alone does not say what stops. */
        .wt-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}

        /* #000 with the 1.5px white stroke: the documented editor-pane treatment the
           two existing code panels already use, rather than the mock's #17191c and a
           grey border. radius 14px matches them too. */
        .wt-window{
          width:100%;height:650px;display:flex;flex-direction:column;overflow:hidden;
          background:#000;border:1.5px solid rgba(255,255,255,.92);border-radius:14px;
          box-shadow:0 30px 80px rgba(0,0,0,.08),0 5px 18px rgba(0,0,0,.04);
          font-family:'SF Mono',Monaco,Consolas,monospace;
        }

        /* Title bar stays light, as in the mock - it reads as chrome around the panel
           rather than part of it. The three lights reuse the existing red and amber
           dots and lime, instead of macOS #ff5f57/#febc2e/#28c840. */
        /* BROWN TITLE BAR, on instruction. It was #fafafa, which made the chrome the
           lightest thing in a section whose subject is a black panel - the bar drew the
           eye before the content did. A dark brown reads as a warm surround to the black
           body instead of a separate light object sitting on top of it, and it is the one
           warm value on the page so it cannot be confused with the lime accent.
           The lights had to be re-derived for it: they were dark alphas chosen for the old
           light bar, and rgba(0,0,0,.16) on brown is nearly the bar itself. Back to white
           alphas, which is correct on a dark surface. */
        /* RIGHT PADDING RESERVES THE PAUSE BUTTON'S FOOTPRINT. .wt-play is absolutely
           positioned, so it is out of flow and would sit on top of .wt-bar-state - measured at
           1280 the two overlapped by 86px, which put "Pause" across "1 foundation". 108px is the
           button's own width plus a gap, so the state text ends before the control begins. */
        .wt-bar{height:47px;flex-shrink:0;display:flex;align-items:center;gap:8px;padding:0 108px 0 15px;background:#3b271a;border-bottom:1px solid rgba(209,244,112,.30)}
        .wt-light{width:11px;height:11px;border-radius:50%;flex:0 0 auto}
        /* LIME AND NEUTRALS ONLY, on instruction. The window lights were red/amber/lime
           borrowed from macOS; the first two are the only warm hues on the page and they
           pulled the eye to chrome rather than to content. Two neutral dots plus one lime
           keeps the traffic-light shape and reads as ours.
           DARK alphas, not white. The first attempt used rgba(255,255,255,.22) and .40 -
           white on a light bar. Composited against this bar's #fafafa those land on
           251,251,251 and 252,252,252: a difference of 1 and 2 out of 255, so both dots
           were invisible and the window appeared to have a single light. The panel BODY is
           black, which is what made white look right in the abstract; the title bar is
           not. Measured with a compositing check rather than judged by eye, and
           brandcheck.js now asserts each light is actually distinguishable from the bar. */
        /* THREE COLOURS AGAIN, AND THIS REVERSES THE EARLIER INSTRUCTION ON PURPOSE.
           Owner picked option 3B from docs/accent-review after seeing the alternatives. The
           note above records why they were neutralised - warm hues on chrome pulling the eye
           away from content - and that reasoning is not wrong, it is now outweighed. Keeping
           the old note rather than deleting it, because a reversal is only informative if what
           it reversed is still readable.

           MEASURED ON THIS BAR (#3b271a), not on white, because the composited background is
           what decides legibility:

             #f0a818 amber    6.92:1
             #9849e8 purple   2.99:1
             #3da35a green    4.42:1
             previous neutrals .26 / .44 -> 2.30:1 and 3.97:1

           PURPLE IS BELOW 3:1 AND THAT IS ACCEPTED HERE, deliberately and with the reason
           written down. A WCAG ratio measures LUMINANCE ONLY; saturated purple against dark
           brown differs strongly in hue and chroma, which the metric does not count, and the
           rendered frame is plainly legible - I checked the picture after writing the number,
           having first told the owner it "sits almost on top of" the bar, which was wrong.
           1.4.11 does not apply regardless: this whole window is aria-hidden decorative chrome
           and carries no state. The two neutrals it replaces were 2.30:1, so this is an
           improvement on what shipped rather than a concession.

           STILL NO ANIMATION. 3C offered a pulse and was not chosen; a permanently breathing
           light in the corner is the WCAG 2.2.2 problem that already removed this panel's
           terminal loop. */
        .wt-light-1{background:#f0a818}
        .wt-light-2{background:#9849e8}
        .wt-light-3{background:#3da35a}
        .wt-bar-title{margin-left:8px;color:rgba(255,255,255,.72);font-size:13px}
        .wt-bar-state{margin-left:auto;display:flex;align-items:center;gap:7px;color:rgba(255,255,255,.58);font-size:12px}
        /* GREEN, NOT LIME, and only this dot changes - see the note below on the two that
           deliberately do not.
           This sits in the same 47px strip as the three window lights, beside the copy
           "8 services · 1 foundation". Once those lights became amber/purple/green it was the
           only lime left in a bar that no longer uses lime, which read as a leftover rather
           than as a colour anyone chose.
           #3da35a is the third light's own value, so no new colour enters the file, and green
           for "8 services healthy" is the one hue here that already means what the sentence
           says. Measured on this bar's #3b271a: 4.42:1, down from lime's 11.32:1. That drop is
           the cost and it is well clear of 3:1 on a 6px decorative dot inside an aria-hidden
           window. */
        .wt-state-dot{width:6px;height:6px;border-radius:50%;background:#3da35a}

        /* min-height:0 is load-bearing on a flex child that scrolls: without it the
           flex item's automatic minimum size is its content, so it refuses to shrink,
           the panel grows past its 650px and nothing ever scrolls. Bottom padding is
           24px now rather than 66px - the 66 was reserving room for a footer that used
           to overlap this box and no longer does. */
        /* THE SCROLLBAR IS VISIBLE, AND THAT IS PART OF THE SAME FIX.
           The thumb was rgba(255,255,255,.24) on a transparent track, over a #000 panel - so
           the channel was invisible and the thumb was close to it. About 800px of the sequence
           scrolls past at 1280 and 1439px on a phone, and nothing indicated that there was
           anything above the visible edge to go back to. Overflow the reader cannot see is
           overflow they will not look for.
           .38 thumb on a .08 track: the track is what makes the region legible as scrollable
           at rest, which the thumb alone does not do. Both are white alphas on the existing
           panel, so no new colour enters. */
        .wt-space{position:relative;flex:1;min-height:0;padding:30px 34px 24px;overflow-y:auto;overflow-x:hidden;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.38) rgba(255,255,255,.08)}
        .wt-space::-webkit-scrollbar{width:7px}
        .wt-space::-webkit-scrollbar-track{background:rgba(255,255,255,.08);border-radius:20px}
        .wt-space::-webkit-scrollbar-thumb{background:rgba(255,255,255,.38);border-radius:20px}

        /* EVERY SIZE IN THIS PANEL WENT UP, on instruction - the code was 10 and 11px,
           which is below what the rest of the site uses anywhere and unreadable on a
           laptop at arm's length. Monospace also runs optically smaller than Inter at the
           same nominal size, so matching the body number would still have read small.
           Floor is now 12px, with the step name and the request line at 15px. */
        .wt-request{margin-bottom:32px;display:flex;gap:10px;color:#fff;font-size:15px;line-height:1.7}
        .wt-caret{color:#d1f470}

        /* Each step fades up as it arrives. The connector is a ::before rule so it
           cannot be knocked out of alignment by content height. */
        /* LIME SEPARATORS, on instruction: the connector spine between steps, the title
           bar underline and the footer rule all carry the accent at low alpha instead of
           neutral white. Low alpha matters - at full strength a 1px lime line down the
           whole panel competes with the lime step dots that mark actual state. */
        .wt-step{position:relative;padding:0 0 29px 36px;opacity:1;transform:translateY(0);animation:wt-in .35s ease both}
        .wt-step::before{content:'';position:absolute;left:5px;top:19px;bottom:-1px;width:1px;background:rgba(209,244,112,.38)}
        .wt-step.is-last::before{display:none}
        @keyframes wt-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

        .wt-dot{position:absolute;left:0;top:4px;width:12px;height:12px;z-index:2;border-radius:50%;border:2px solid rgba(255,255,255,.34);background:#000}

        /* ONE HUE PER SERVICE, and this is a system rather than decoration - which is the
           difference that makes it defensible here after the window lights took three colours.
           Each step IS a named service (gateway, auth, contacts, messaging, commerce, billing,
           queue, platform), so a hue that identifies the service is the same use the rotating
           hero pill puts this palette to: one colour per subject.

           STATE IS STILL NOT CARRIED BY HUE, which is the constraint that had to hold. Before
           this, lime meant "ran", so the hue was doing two jobs at once. What separates the two
           states now:
             running   pulsing
             done      static
           plus a completed row carries a tick, and the footer reads "running" / "complete" in
           words. Three non-colour signals, so WCAG 1.4.1 is not engaged: hue says WHICH service,
           motion and text say WHETHER it ran.

           THIS LINE USED TO CLAIM ".wt-name.is-complete turns the service name lime", and both
           halves went stale as the panel changed: the rule moved off lime onto the step's own
           hue, and then off the name entirely when option A was chosen. Names are #fff on all
           eight rows now - see the note beside .wt-tick. Corrected rather than deleted because
           the count of non-colour signals is the load-bearing part of this paragraph.

           The hollow .wt-dot default above is a fallback that NO rendered step uses - the
           component assigns every visible step either is-done or is-running
           (state = i <= settled ? 'is-done' : 'is-running'), so there is no pending dot on
           screen to distinguish. Worth stating because "pending is hollow" is the obvious thing
           to assume from reading the CSS alone, and it would be wrong.

           MEASURED ON THE PANEL BODY #000, every value already in this repo:
             lime   #d1f470  16.89:1    amber #f0a818  10.32:1
             green  #3da35a   6.58:1    purple #9849e8  4.45:1
             blue   #2563eb   4.06:1    red    #dc2626  4.35:1

           RED IS EXCLUDED DELIBERATELY, and it is the only one that clears contrast and is
           still wrong. Step 7 reads "A provider failed, nobody noticed" - the whole point of
           that line is that the failure was absorbed - and step 6 is "Usage metered". A red dot
           on either reads as an alarm about the thing being described. Five hues cycle instead,
           ordered so no two adjacent steps repeat, and step 8 "All services healthy" lands on
           green because that is the one hue whose convention matches its sentence. */
        /* THREE PROPERTIES PER STEP, FROM ONE SOURCE OF TRUTH.
           --rgb   the hue as bare channels, so a tint can be mixed with rgba() without a
                   second literal to keep in sync. There is no color-mix() anywhere in this
                   repo and no browserslist declaring support for it, so rgba(var(--rgb),a)
                   is the portable way to get "this hue at 14%" - it works wherever custom
                   properties do, which is everywhere this site is served.
           --dot   the solid hue, derived. Substitution happens before the value is parsed,
                   so rgb(var(--rgb)) resolves to rgb(37,99,235) and every existing
                   var(--dot) usage keeps working untouched.
           --ink   the same hue LIFTED until it is legible as text. Defaults to --dot and is
                   overridden only where it has to be - see the note on --ink below.

           Deriving --dot rather than listing both is deliberate: a hex and a channel triple
           for the same colour is two things to edit and one to forget. */
        .wt-step{--rgb:209,244,112;--dot:rgb(var(--rgb));--ink:var(--dot)}
        /* --ink EXISTS BECAUSE TWO OF THE FIVE HUES ARE NOT LEGIBLE AS TEXT ON #000, and the
           comment this replaces got that wrong in writing. It said the lowest of the five was
           "blue at 4.06:1. Well clear of 4.5:1 for 15px/600 text". 4.06 is not clear of 4.5,
           it is BELOW it - so the rule as shipped was a latent AA failure waiting for a data
           change: mark step 1 or 6 complete and its name renders blue at 4.06:1. Nothing was
           visibly broken only because step 8, the single complete step, happens to be green.
           Purple was the same story with less margin to spare, at 4.45:1.

           The lift is the smallest that clears 4.5:1 on the pill's own tinted background:
             blue    #2563eb -> #3d74ed   4.51:1   11% toward white
             purple  #9849e8 -> #9f56ea   4.56:1    7% toward white
             amber, lime, green unchanged - they already clear it at 8.60, 13.10 and 5.78:1
           11% and 7% are small enough that the dot and its pill read as the same colour: blue
           moves 43 of a possible 765 in RGB distance. And the five inks stay distinguishable
           from each other - the closest pair, blue and purple, is 131 apart. */
        .wt-step:nth-child(1){--rgb:37,99,235;--ink:#3d74ed}
        .wt-step:nth-child(2){--rgb:152,73,232;--ink:#9f56ea}
        .wt-step:nth-child(3){--rgb:240,168,24}
        .wt-step:nth-child(4){--rgb:209,244,112}
        .wt-step:nth-child(5){--rgb:61,163,90}
        .wt-step:nth-child(6){--rgb:37,99,235;--ink:#3d74ed}
        .wt-step:nth-child(7){--rgb:240,168,24}
        .wt-step:nth-child(8){--rgb:61,163,90}

        /* Running fills and pulses; done fills. The glow is NEUTRAL white at .10 rather than
           the lime rgba(209,244,112,.14) it was: a lime halo around a blue or purple dot reads
           as two colours fighting, and a per-hue halo would need a second variable for every
           step to say the same thing a neutral one says once. */
        .wt-step.is-running .wt-dot{border-color:var(--dot);background:var(--dot);box-shadow:0 0 0 4px rgba(255,255,255,.10);animation:wt-pulse 1.2s ease-in-out infinite}
        .wt-step.is-done .wt-dot{border-color:var(--dot);background:var(--dot)}
        @keyframes wt-pulse{0%,100%{opacity:.5;transform:scale(.85)}50%{opacity:1;transform:scale(1)}}

        .wt-head{min-height:20px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
        /* The service name is the new first-class thing in each row: the panel's subject
           is which service ran, not which phase of a plan it was.

           THE PILL NOW CARRIES ITS SERVICE'S OWN HUE, and this reverses an earlier call.
           It was lime on all eight, with the reasoning that "giving it five colours would
           turn a label into a legend the reader is expected to decode". Owner overruled it,
           three times, and on reflection the objection was answering the wrong question.
           This pill contains the service's own name - gateway, auth, contacts - so it IS the
           service identity, which is precisely what the dot hue encodes. Lime on all eight meant the
           one element naming the service was the one element refusing to colour it, and lime
           there had stopped meaning anything at all: it was the last survivor of the old
           "lime = ran" scheme that the per-service dots replaced.

           Nothing is asked of the reader that was not already asked. The hue is not a legend
           to decode because the pill spells the service out in words beside it; colour is
           redundant reinforcement of text that is already there, which is the one use of
           colour that costs a reader nothing.

           THE LABEL IS WHITE. THE HUE IS THE CHIP AROUND IT. This is a correction, and the
           thing it corrects was mine: the label used to be var(--ink) on a 14% ground of its own
           hue, which passed 4.5:1 and was still hard to read. Owner reported it on the auth
           chip specifically, and the numbers say exactly that:

             gateway   #3d74ed on #050e21   4.51:1    bare pass
             auth      #9f56ea on #150a20   4.56:1    bare pass
             commerce  #3da35a on #09170d   5.78:1    middling
             contacts  #f0a818 on #221803   8.60:1    fine
             messaging #d1f470 on #1d2210  13.10:1    fine

           4.5:1 IS A FLOOR WRITTEN FOR ~16px TEXT. This label is 11.5px. Clearing the floor by
           0.01 and 0.06 at three quarters of that size is a pass on paper and a squint in
           practice, and only two of the five hues had any real headroom - so the set was also
           visibly uneven, two crisp chips and two murky ones.

           Lifting the inks to 7:1 was the obvious fix and is worse. Blue needs 36% toward white
           and moves 141 of 765 in RGB distance from its own dot; purple needs 33%. Amber and
           lime need 0%. The result is a half-pastel set where some chips match their dot and
           others have drifted off it.

           White costs nothing and is even: 19.24, 19.16, 17.50, 16.30 and 18.42:1 at the old
           alphas - the WORST of them is better than the best hue-ink chip was. Raising the
           ground to .20 and the border to .60 trades a little of that back for a chip whose hue
           is unmistakable at a glance, and the lowest is still 13.55:1 on messaging. All five
           grounds stay separable from each other, so the chips remain distinguishable by fill
           as well as by border.

           Identity is not lost by taking hue off these 11.5px letters. It is carried twice over
           by things that have no legibility floor at all: the 12px solid dot and the chip's own
           fill and border. This is the same principle option A settled for the step names -
           hue belongs on shapes, text belongs at maximum contrast - applied one level down.

           --ink SURVIVES for .wt-tick, which still needs a legible hue. */
        .wt-svc{padding:2px 7px;border-radius:4px;background:rgba(var(--rgb),.20);border:1px solid rgba(var(--rgb),.60);color:#fff;font-size:11.5px;letter-spacing:.02em}
        .wt-name{color:#fff;font-size:15px;font-weight:600}
        /* THE TICK TAKES THE STEP'S OWN HUE. THE NAME STAYS WHITE ON ALL EIGHT ROWS.
           Both the name and the tick were #d1f470 while the dots were lime too, so the row
           agreed with itself. Once the dots became one hue per service, lime here was the last
           thing in the panel still claiming the old meaning - and measured, only ONE row was
           affected, because the rule is gated on step.complete and step 8 is the only step whose
           data sets it. Names were #fff on steps 1-7 and lime on step 8 alone. That is why the
           recolour was reported as "not showing": it moved a single line from lime to green, two
           greens, while all eight .wt-svc pills stayed lime. "The text is still lime" was three
           separate things - this name, this tick, and the pill - and the pill was the one the
           report was actually looking at.

           THE PILL IS NOW IN THE SAME SCHEME - see the note on .wt-svc. It used to be excluded
           and held lime on all eight, which meant this rule recoloured exactly ONE line in the
           whole panel (step 8, the only step whose data says complete:true) while the eight
           pills stayed lime. That is why the change was reported as "not showing" after it
           shipped correct: it was a single row moving from lime to green, two greens, against
           eight unchanged lime chips.

           THE NAME IS NO LONGER IN THIS RULE. Owner picked option A from docs/step-review.md
           after seeing all five panels rendered, and the deciding argument only became visible
           once they were pictures rather than contrast figures:

           ON A SENTENCE, A HUE STOPS READING AS AN IDENTIFIER AND STARTS READING AS A SEVERITY.
           Colouring all eight names put step 7, "A provider failed, nobody noticed", in amber -
           which reads as a warning badge, when the entire point of that line is that the failure
           was absorbed and needed no attention. Step 6, "Usage metered", came out blue, which
           reads as an info notice. That is the same reasoning already recorded above for
           EXCLUDING RED from the dot palette, and it applies with more force to a full sentence
           than to a 12px dot.

           The pill does not have the problem and the distinction is worth stating: a chip
           containing the single word "queue" is self-evidently an identifier and cannot be
           mistaken for a severity, because it is not a claim about anything. The sentence beside
           it can be. So hue lives on the dot and the chip - two labels - and never on prose.

           WHAT THIS BUYS. Every name holds #fff at 21:1, the most readable text on the panel,
           and step 8 stops being the one visibly dim row: it used to be the ONLY name that left
           white, which is why recolouring it read as a defect rather than as a signal. "Complete"
           is still carried three ways without colour - the tick below, the dot going static
           instead of pulsing, and the footer's "running"/"complete" wording - so WCAG 1.4.1
           stays unengaged and nothing that colour was uniquely saying has been lost.

           .is-complete IS DELIBERATELY STILL IN THE MARKUP with no paint of its own. It is the
           DOM's record of which step finished, tools/browser/replaycheck.js reads it to report
           the per-row colour table, and dropping it to tidy up an unused selector would blind
           that probe to the state it exists to measure.

           THE TICK KEEPS --ink, NOT --dot, and that is a latent AA fix rather than a preference.
           Raw blue is 4.06:1 on #000 and raw purple 4.45:1, both under the 4.5:1 floor for text
           this size, so a tick on a completed blue or billing step would have shipped failing.
           --ink is the same hue lifted just past the floor and is identity for amber, lime and
           green, so the tick on step 8 is pixel-identical to what it rendered before. */
        .wt-tick{color:var(--ink)}
        /* .46 IS 4.58:1 ON THIS PANEL - eight hundredths above the 4.5:1 floor for text this
           size, and the tightest margin anywhere on the home page. Left alone deliberately,
           and the reason is the rung below it: .wt-infra was raised from .44 to .50 when it
           failed, and a timestamp has to stay dimmer than the infrastructure line or the two
           read as equals. Moving this to .50 would collapse that distinction to fix a value
           that already passes. What it must not do is drift DOWN: .45 is 4.47:1 and fails, so
           there is no headroom here at all. flowprobe.js asserts the measured ratio, which is
           why a one-notch nudge cannot land quietly. */
        .wt-time{color:rgba(255,255,255,.46);font-size:12px}
        .wt-desc{max-width:780px;margin:7px 0 0;color:rgba(255,255,255,.62);font-size:13.5px;line-height:1.65}

        .wt-cmd{margin-top:11px;padding:12px 14px;overflow-x:auto;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.14);border-radius:7px;color:#fff;font-size:13.5px;line-height:1.7;white-space:nowrap}
        .wt-sh{margin-right:7px;color:rgba(255,255,255,.46)}
        .wt-fn{color:#d1f470}
        .wt-str{color:rgba(255,255,255,.76)}
        .wt-key{color:rgba(255,255,255,.58)}
        .wt-num{color:#d1f470}
        .wt-cm{color:rgba(255,255,255,.46)}

        /* The infra comment. Dim on purpose - it is the substrate, not the event - but
           still above the 12px floor because it carries the actual message.
           .50, NOT .44, AND THE REASON IS MEASURED. This line is the one that makes the
           section's argument - "# dynamodb · single-table · on-demand capacity", the shared
           foundation named under every step - and at rgba(255,255,255,.44) it composited to
           4.25:1 on #000, below the 4.5:1 WCAG 1.4.3 requires at 12.5px/400. It was the only
           one of the fourteen text styles in this panel that failed; .50 measures 5.28:1.
           Deliberately NOT .62: that is .wt-desc's value, and this line must stay dimmer than
           the description it sits under, which is the whole point of the "dim on purpose"
           above. .50 is the smallest step that clears AA and keeps that order intact.
           NOTE .wt-cm above passes at 4.58:1, i.e. by 0.08 - any further dimming of it fails.
           Re-measure with: node tools/browser/flowprobe.js - it asserts every ratio here.
           (No backticks in this comment: this sits inside a style jsx template literal, where
           one stray backtick ends the literal and the build fails at type-check.) */
        .wt-infra{margin-top:9px;color:rgba(255,255,255,.50);font-size:12.5px;line-height:1.6}

        .wt-results{margin-top:11px;display:flex;flex-wrap:wrap;gap:7px}
        .wt-chip{padding:5px 9px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.14);border-radius:5px;color:rgba(255,255,255,.62);font-size:12px}
        .wt-chip.is-ok{color:#d1f470;border-color:rgba(209,244,112,.34)}
        /* A warning is carried by weight, not by a second hue: brighter text on a
           brighter border, still neutral, so lime stays the only accent in the panel body. */
        .wt-chip.is-warn{color:rgba(255,255,255,.92);border-color:rgba(255,255,255,.38)}

        /* CONCURRENCY, SHOWN AS COLUMNS. auto-fit rather than a fixed four so the lanes
           wrap to two-by-two on a narrow panel instead of overflowing - they still read as
           simultaneous, which a horizontal scrollbar would destroy. */
        .wt-lanes{margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:8px}
        .wt-lane{padding:9px 10px;background:rgba(255,255,255,.04);border:1px solid rgba(209,244,112,.22);border-radius:6px;display:flex;flex-direction:column;gap:3px}
        /* A short lime rule at the top of each lane, so the four read as parallel tracks
           starting together rather than as four unrelated cards. */
        .wt-lane-bar{display:block;width:22px;height:2px;border-radius:2px;background:#d1f470;margin-bottom:3px}
        .wt-lane-name{color:#fff;font-size:12.5px;font-weight:600}
        .wt-lane-detail{color:rgba(255,255,255,.54);font-size:12px;line-height:1.45}

        .wt-checks{margin-top:11px;display:grid;gap:8px}
        .wt-check{display:flex;align-items:center;gap:8px;color:rgba(255,255,255,.62);font-size:12.5px}
        .wt-check-tick{color:#d1f470}

        /* Fades the stream out under the footer rather than letting rows collide with
           it. The gradient has to end in the panel's own #000 or it shows a seam. */
        .wt-foot{flex:0 0 auto;height:50px;padding:0 24px;display:flex;align-items:center;background:#000;border-top:1px solid rgba(209,244,112,.30);color:rgba(255,255,255,.54);font-size:12px}
        .wt-foot-left{display:flex;align-items:center;gap:7px}
        /* STAYS LIME, DELIBERATELY, and this is the boundary of the recolour.
           This dot sits beside "running" / "complete" on the BLACK footer, not the brown title
           bar, and it reports live state - it is the same claim the lime .wt-dot step markers
           make inside the panel, where lime means "this service ran". The title-bar lights are
           decorative chrome and could take any hue; these two are the panel's only actual
           signal, and recolouring them would spend the accent on decoration and leave the
           meaning without a colour of its own. Lime on #000 is 11.90:1 here.
           If the owner wants this one moved too it is one line - but it should be moved knowing
           it takes the step dots with it, or the footer and the steps stop agreeing. */
        .wt-foot-dot{width:5px;height:5px;border-radius:50%;background:#d1f470}
        .wt-foot-right{margin-left:auto}

        @media(max-width:767px){
          .wt-window{height:min(560px,calc(100vh - 180px));border-radius:12px}
          .wt-space{padding:23px 18px 60px}
          .wt-bar-state{display:none}
          .wt-step{padding-left:29px}
          .wt-request{font-size:12px}
        }

        /* Reduced motion starts on the finished state with the loop paused, so by default this
           only has to stop the decorative loops. It also holds if that reader presses Play: the
           steps still advance, because that is the content, but the entrance slide and the dot
           pulse stay off. Asking to see the sequence is not the same as asking for the
           flourishes around it, and the OS preference is still the tie-breaker on those. */
        @media(prefers-reduced-motion:reduce){
          .wt-step{animation:none}
          .wt-step.is-running .wt-dot{animation:none}
          .wt-space{scroll-behavior:auto}
        }
      `}</style>
    </section>
  );
};

export default WorkflowTerminal;
