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
type Lane = { name: string; detail: string; on?: boolean };

interface Step {
  /** The service that did the work, shown as the lane label. */
  service: string;
  name: string;
  description: string;
  time: string;
  /** Shared infrastructure this step ran on, rendered as a code comment. */
  infra?: string;
  command?: React.ReactNode;
  /** The inline AI decision for this step, e.g. 'intent read -> order confirmation'.
      Rendered as the lime "ai >" thread marker plus white decision text. Steps that are
      deliberately NOT AI (01, 02, 09) carry no ai field - that honesty boundary is the point. */
  ai?: string;
  /** A small indented micro-trace under the step (step 06's draft provenance, step 09's retry). */
  subtrace?: string[];
  results?: Result[];
  /** Concurrent services. Rendered as parallel lanes, not a sequence. */
  lanes?: Lane[];
  checks?: string[];
  complete?: boolean;
}

/**
 * WHAT THIS PANEL SAYS ABOUT THE COMPANY, which is the whole reason it was rewritten AGAIN.
 *
 * THIS REVERSES THE PANEL'S PREVIOUS DECISION, on owner instruction (recorded learning
 * 75c80121-7ead-4c49-b900-a0817515f2db). The panel used to be a deliberately NOT-AI
 * infrastructure trace: eight services on one shared platform, with a note that "AI is a
 * feature inside a few of them rather than the thing being sold". The owner has decided the
 * opposite framing is the one to ship: this is a 10-service AI-EXECUTION trace that shows
 * AI AT EVERY DECISION. The reversal is kept visible the way this file keeps every reversal
 * readable - the prior reasoning is not deleted elsewhere, it is simply outranked here.
 *
 * So the stream now shows one order (#WD-4821) executing end to end, and at each step that
 * involves a judgement the panel names the AI decision inline with a lime "ai >" marker:
 * the intent is read, the request is validated, the transaction is risk-checked, the reply
 * is drafted from the knowledge base, channels are selected and tailored, a follow-up is
 * judged warranted, and the whole run is verified against one model. AI understands and
 * decides; the platform executes.
 *
 * THE HONESTY BOUNDARY IS DELIBERATE. Three steps carry NO ai marker on purpose - gateway
 * accepting the request (01), auth verifying access (02), and the queue recovering a failed
 * send (09). Those are platform resilience, not intelligence, and claiming AI there would be
 * the kind of overreach the panel is careful to avoid. Six steps carry an ai decision, which
 * is the "AI at 6 decisions" the done footer reports.
 *
 * THE INFRA/SUB-TRACE LINES carry the detail. Step 06 shows the draft's provenance as a
 * four-line micro-trace; step 09 shows the retry sequence; step 10 rolls up the verification
 * checks. The parallel lanes in the messaging step (07) show the five channel OPTIONS
 * evaluated at once - a vertical list would have read as five more sequential steps, which is
 * precisely the wrong impression.
 *
 * Nothing here claims a benchmark. The timings are illustrative - the sub-caption says so in
 * words - and the panel is aria-hidden with a static summary, so no assistive technology is
 * told these are measurements.
 */
const STEPS: Step[] = [
  {
    service: 'gateway', name: 'REQUEST ACCEPTED', time: '12ms',
    description: 'Order #WD-4821 arrives over one secure connection.',
    results: [ { label: 'received' }, { label: 'routed' } ],
  },
  {
    service: 'auth', name: 'ACCESS VERIFIED', time: '31ms',
    description: 'Identity verified. Account boundaries enforced.',
    results: [ { label: 'authorized', kind: 'ok' }, { label: 'tenant isolated' } ],
  },
  {
    service: 'contacts', name: 'CONTEXT LOADED', time: '18ms',
    description: 'Customer, history and consent resolved in one read.',
    ai: 'intent read → order confirmation',
    results: [ { label: 'context ready', kind: 'ok' }, { label: 'intent known' } ],
  },
  {
    service: 'commerce', name: 'ORDER COMMITTED', time: '54ms',
    description: 'Order confirmed, inventory adjusted, in one write.',
    ai: 'request validated against order',
    results: [ { label: '#WD-4821 confirmed', kind: 'ok' }, { label: 'stock −1' } ],
  },
  {
    service: 'payments', name: 'PAYMENT CAPTURED', time: '240ms',
    description: 'Payment captured; invoice issued against the order.',
    ai: 'transaction risk-checked → clear',
    results: [ { label: 'paid', kind: 'ok' }, { label: 'invoice #INV-4821' } ],
  },
  {
    service: 'ai', name: 'RESPONSE GENERATED', time: '420ms',
    description: 'AI drafts the reply, grounded in our knowledge base.',
    ai: 'drafted from 2 sources',
    subtrace: [
      'intent → order confirmation',
      'context → customer + order',
      'knowledge → 2 sources',
      'output → response drafted',
    ],
    results: [ { label: 'draft ready', kind: 'ok' } ],
  },
  {
    service: 'messaging', name: 'CHANNELS ORCHESTRATED', time: '46ms',
    description: 'Eligible channels dispatched independently.',
    ai: 'selected channels · tailored each',
    infra: 'one messaging foundation, five channel options',
    lanes: [
      { name: 'whatsapp', detail: 'Delivered', on: true },
      { name: 'rcs', detail: 'Available · not selected', on: true },
      { name: 'sms', detail: 'Sent', on: true },
      { name: 'email', detail: 'Sent', on: true },
      { name: 'voice', detail: 'Skipped', on: false },
    ],
    results: [ { label: 'parallel dispatch', kind: 'ok' }, { label: 'tracked' } ],
  },
  {
    service: 'automation', name: 'RULES APPLIED', time: '11ms',
    description: 'A follow-up fires on its own.',
    ai: 'follow-up judged warranted',
    results: [ { label: '1 rule matched', kind: 'ok' }, { label: 'scheduled' } ],
  },
  {
    service: 'queue', name: 'FAILURE RECOVERED', time: '1.2s',
    description: 'A failed send retried safely and delivered.',
    subtrace: [ '503 → backoff → retry 2/5 → accepted' ],
    results: [ { label: 'retry handled', kind: 'warn' }, { label: 'accepted', kind: 'ok' } ],
  },
  {
    service: 'platform', name: 'EXECUTION VERIFIED', time: '2.1s', complete: true,
    description: 'One AI, every service, one foundation.',
    ai: 'one model across all of it',
    checks: [ 'order', 'payment', 'AI response', 'channels', 'rules', 'recovery', 'one foundation' ],
    results: [ { label: 'one shared foundation', kind: 'ok' } ],
  },
];

// Per-step dwell: richer steps hold longer so there is time to read them. Keyed off what
// the step contains rather than its index, so reordering STEPS does not silently retime
// the sequence.
const dwell = ( step: Step ): number => {
  if ( step.lanes ) return 1350;
  if ( step.complete ) return 1350;
  if ( step.checks ) return 1200;
  if ( step.command ) return 1200;
  if ( step.subtrace ) return 1200;
  return 900;
};

/**
 * HOW MANY COMPLETED RUNS BEFORE THE LOOP STOPS ON ITS OWN.
 *
 * The panel used to loop forever, which is the WCAG 2.2.2 case the Pause control exists to
 * answer. Stopping on the finished state after a few passes is strictly better for 2.2.2 - the
 * motion ends by itself, well before "forever" - while keeping the control working during the
 * passes. Two is enough for the point to land (a visitor sees a completed run, then watches it
 * replay once) without becoming perpetual. One named const so the count is easy to retune.
 *
 * COUNTING, because the off-by-one is not obvious. `cycle` starts at 0 and is bumped once per
 * RESTART, so it counts restarts, not passes. The visitor's FIRST completed run is the static
 * finished state the panel renders on load and holds for 3.2s during the cycle-0 effect run -
 * see the resumeRef note: "a visitor therefore reads a completed run first". With MAX_CYCLES 2:
 *   cycle 0  -> 1st completed run (the initial static hold)        -> restart -> cycle 1
 *   cycle 1  -> 2nd completed run (the one streamed replay)        -> STOP, hold the finished state
 * Two completed runs land when cycle reaches MAX_CYCLES - 1, so the end-of-pass branch restarts
 * only while cycle < MAX_CYCLES - 1. At cycle === MAX_CYCLES - 1 it leaves `done` true and does not
 * bump `cycle`, so the panel holds the finished state - byte-identical to the initial and
 * reduced-motion render, and the never-empty invariant is untouched because `shown` never rewinds.
 * Dropped 3 -> 2 with the longer 10-step trace: the visitor sees the completed run, then watches
 * it stream through once, which is enough for the point to land without the panel moving for a
 * third pass over a sequence that now runs ~16-18s per pass.
 */
const MAX_CYCLES = 2;

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
   * HTML: a grep for the first step's name in out/index.html returned 0, and with JavaScript
   * disabled the largest element on the home page was a 650px black rectangle holding one line
   * of text and a footer reading "running 0 / 10 services". Every word of the ten steps existed
   * only after hydration, so a no-JS reader, a WebView with scripting off, and anything reading
   * the HTML rather than running it all got an empty panel - on the same site that just started
   * publishing llms.txt and an /mcp endpoint for exactly those readers.
   *
   * Shipping the COMPLETE state fixes it with no new markup: ten rows, all settled, footer
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
  /* The loop now stops on its own after MAX_CYCLES completed runs - see the const. `stopped`
   * marks that natural end so the control can relabel to "Replay" and start a fresh capped run
   * rather than sit inert on a panel that will never move again. It is NOT in the stepping
   * effect's dependency list on purpose: it is set from a timeout callback (like setDone and
   * setCycle beside it) and read only by the control and the render, so it drives no extra
   * re-run of the effect and needs no exhaustive-deps suppression. */
  const [ stopped, setStopped ] = useState( false );
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
  //   2. is answered by never rewinding `shown`. Only `settled` rewinds, so all ten rows stay
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
        /* THE LOOP STOPS HERE ONCE IT HAS SHOWN MAX_CYCLES COMPLETED RUNS. `cycle` counts
         * restarts and the initial static complete state is the first completed run (cycle 0),
         * so the second (final) run lands when cycle reaches MAX_CYCLES - 1 - see the const's
         * counting note for the full off-by-one. At that point we schedule NO restart: `done` stays true,
         * `cycle` is not bumped, and the finished state holds. No timer is left pending, so the
         * cancelled/clearTimeout cleanup stays correct. `stopped` flips the control to "Replay".
         * The never-empty invariant is preserved: `shown` was never rewound, so all ten rows
         * remain mounted and settled - the exact frame of the initial and reduced-motion render. */
        if ( cycle >= MAX_CYCLES - 1 ) {
          setStopped( true );
          return;
        }
        /*
         * IT LOOPS AGAIN, ON OWNER INSTRUCTION - BUT NOT THE LOOP THAT WAS REMOVED.
         *
         * The old loop reset `shown` to 0, and that is the defect recorded above: the panel
         * dropped to a single 26px line inside a 551px box, 95% empty, every 15.8s, so the
         * largest element on the home page periodically showed nothing and anyone arriving
         * mid-reset met a black rectangle.
         *
         * THIS RESTART LEAVES `shown` AT STEPS.length AND ONLY REWINDS `settled`. All ten
         * rows stay mounted and on screen for the entire cycle; what replays is the
         * running-to-done pass travelling down them. The panel is never empty at any point,
         * which is the whole objection answered rather than accepted.
         *
         * What a reader sees at the restart edge is the stack going live at once and then
         * settling row by row - a heartbeat rather than a rebuild. Stated because ten dots
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
      // Only the first pass reveals rows. Every later pass finds all ten already mounted,
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
    /* REPLAY AFTER A NATURAL STOP. Once the loop has stopped on its own the control is not a
     * Pause/Play toggle any more - there is nothing running to pause and `paused` is false - so
     * a plain toggle would only PAUSE a stopped machine and leave the button inert. Instead the
     * control reads "Replay" and this branch starts a fresh capped run: rewind the frontier the
     * same way the paused-at-end Play branch below does, clear `stopped`, and reset the pass
     * counter by setting `cycle` back to 0. The cycle change re-enters the stepping effect and
     * plays another MAX_CYCLES-run sequence from the top. `paused` is left false, so the run
     * begins at once. `followRef` is deliberately not written here - the same react-hooks
     * immutability rule that keeps it out of the end-of-pass restart (see that note) applies, and
     * the follow effect reclaims the frontier on the next settle regardless. */
    if ( stopped ) {
      resumeRef.current = 0;
      setDone( false );
      setSettled( -1 );
      setStopped( false );
      setCycle( 0 );
      return;
    }
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
          screen reader should not receive ten nodes appearing on timers. */}
      <p className="wt-sr">
        An illustration of one customer order moving through our services with AI at each
        decision: the request is accepted, access is verified, the customer context is loaded
        while AI reads the intent, the order is committed, payment is captured, AI generates a
        response grounded in our knowledge base, five channels are evaluated and the eligible
        ones deliver, an automation rule fires a follow-up on its own, a failed send is retried
        and confirmed by the platform, and all ten services report healthy — the AI
        understands, decides and drafts while the platform executes, every one of them on the
        same shared foundation.
      </p>

      {/* dir="ltr" LOCKS THE TERMINAL, and it is a correctness fix rather than a preference.
          This panel draws literal machine output - a shell prompt, "platform · illustration",
          an "ai >" decision thread, "503 -> backoff -> retry 2/5 -> accepted". None of that is
          prose and none of it is left-to-right by convention: it is left-to-right by SYNTAX.
          With the
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
          The window carries aria-hidden="true" because a screen reader should not receive ten
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
          /* THREE LABELS, ONE CONTROL. Pause while playing, Play while paused mid-run, and
             Replay once the loop has stopped on its own after MAX_CYCLES. The triangle mark is
             shown for both Play and Replay (is-paused), because both start motion; only the
             running state shows the two pause bars. aria-pressed is a toggle state and only
             means something for Pause/Play, so it is false at the natural stop where the control
             is a one-shot Replay rather than a toggle. */
          className={ `wt-play ${( paused || stopped ) ? 'is-paused' : ''}`.trim() }
          onClick={ togglePlay }
          aria-pressed={ stopped ? false : paused }
        >
          <span className="wt-play-mark" aria-hidden="true" />
          { stopped ? 'Replay' : ( paused ? 'Play' : 'Pause' ) }
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
          <span className="wt-bar-title">platform · illustration</span>
          <span className="wt-bar-state"><i className="wt-state-dot" />live trace</span>
        </div>

        <div className="wt-space">
          <div className="wt-request"><span className="wt-caret">›</span><span>One request. Intelligence at every decision.</span></div>
          {/* Illustrative-trace caption. Verbatim UI copy from the locked spec; the em dash is
              intentional and part of that string, not prose written here. Smaller and dimmer
              than .wt-request so it reads as a subordinate caption. */}
          <div className="wt-caption">Illustrative trace — timings are not measured.</div>

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

                  { /* THE INLINE AI DECISION, inline in the map on purpose - styled-jsx only
                       scopes elements statically present in this return tree, so building this
                       in a helper would silently drop every .wt-ai rule. The "ai >" tag is the
                       one place lime is spent in the panel body as a thread marker; the decision
                       TEXT stays white so it reads as a sentence, not an accent. Steps 01/02/09
                       carry no ai field, so this renders nothing on them - the honesty boundary. */ }
                  { step.ai && (
                    <div className="wt-ai">
                      <span className="wt-ai-tag">ai ▸</span>
                      <span className="wt-ai-text">{ step.ai }</span>
                    </div>
                  ) }

                  { step.command && <div className="wt-cmd">{ step.command }</div> }

                  { /* The shared foundation, written the way it would appear in code. This
                       is the line that carries the actual claim: different services,
                       same infrastructure underneath. */ }
                  { step.infra && <div className="wt-infra"># { step.infra }</div> }

                  { /* THE MICRO-TRACE, inline in the map for the same styled-jsx reason as the
                       ai marker. Step 06 shows the draft's provenance (four lines); step 09 shows
                       the retry sequence (one line). A small indented muted monospace block that
                       reads as a detail under the step. */ }
                  { step.subtrace && (
                    <div className="wt-subtrace">
                      { step.subtrace.map( line => (
                        <div key={ line } className="wt-subtrace-line">{ line }</div>
                      ) ) }
                    </div>
                  ) }

                  { step.results && (
                    <div className="wt-results">
                      { step.results.map( r => (
                        <span key={ r.label } className={ `wt-chip ${r.kind ? 'is-' + r.kind : ''}`.trim() }>{ r.label }</span>
                      ) ) }
                    </div>
                  ) }

                  { /* PARALLEL LANES, side by side on purpose. Stacked vertically these
                       five would read as five more sequential steps, which is the exact
                       opposite of the point - they run at the same time. Each lane carries a
                       CSS-drawn status dot: green for a channel that was used, a hollow/dimmed
                       white dot for one that was available but not selected (voice). */ }
                  { step.lanes && (
                    <div className="wt-lanes">
                      { step.lanes.map( lane => (
                        <div key={ lane.name } className="wt-lane">
                          <span className="wt-lane-bar" />
                          <span className="wt-lane-head">
                            <span className={ `wt-lane-dot ${lane.on ? 'is-on' : 'is-off'}` } />
                            <span className="wt-lane-name">{ lane.name }</span>
                          </span>
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
        {/* THE COUNT LIVES ONLY HERE. The chrome bar dropped its count, so this is the one
            place the panel reports progress. Running: the left is the lime dot + "running"
            and the right counts up `${shown} / ${STEPS.length} services` - with ten steps
            STEPS.length is 10, so it animates 1 / 10 -> 10 / 10 as each row settles, driven by
            `shown` and frozen while paused because the stepper that advances `shown` is gated by
            the pause control. Done: a single CSS-safe tick + the locked done string. The "10 / 10"
            is still derived from STEPS.length (the live counter), the rest of the descriptors are
            literal: AI fires at 6 of the 10 steps, one retry was handled, order #WD-4821. */}
        <div className="wt-foot">
          { done ? (
            <span className="wt-foot-left">
              <span className="wt-check-tick">✓</span>
              EXECUTION COMPLETE — { STEPS.length } / { STEPS.length } services · AI at 6 decisions · 1 retry handled · order #WD-4821
            </span>
          ) : (
            <>
              <span className="wt-foot-left"><i className="wt-foot-dot" />running</span>
              <span className="wt-foot-right">{ `${shown} / ${STEPS.length} services` }</span>
            </>
          ) }
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
          font:inherit;font-size:13px;letter-spacing:.02em;color:#f2efe9;
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
        /* CHROME STATUS LEGIBILITY (user: the browser-chrome title and the footer "N / 10"
           status read as the same faint grey and blended into the panel). These are window
           chrome, not body prose, so they are raised toward a solidly-legible muted white by
           OPACITY ONLY (no new hex, palette unchanged): .wt-bar-title .80 -> .88, .wt-bar-state
           .70 -> .86. Both stay BELOW the solid-#fff step content so the content headings remain
           the loudest glyphs; sizes are untouched (title stays 14px, state stays the 13.5px
           small-text floor). .88/.86 on #000 clear AA comfortably (~18:1 / ~17:1). */
        .wt-bar-title{margin-left:8px;color:rgba(255,255,255,.88);font-size:14px}
        .wt-bar-state{margin-left:auto;display:flex;align-items:center;gap:7px;color:rgba(255,255,255,.86);font-size:13.5px}
        /* GREEN, NOT LIME, and only this dot changes - see the note below on the two that
           deliberately do not.
           This sits in the same 47px strip as the three window lights, beside the chrome copy
           "live trace" (the count that used to live here moved to the footer). Once those lights
           became amber/purple/green it was the only lime left in a bar that no longer uses lime,
           which read as a leftover rather than as a colour anyone chose.
           #3da35a is the third light's own value, so no new colour enters the file, and green
           for a "live trace" status is the one hue here that already means "healthy/running".
           Measured on this bar's #3b271a: 4.42:1, down from lime's 11.32:1. That drop is
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
           SIZES RAISED AGAIN, on owner instruction: the panel read too small on both
           desktop and - worse - on a phone, where the request line had been dropped BELOW
           its desktop size. The floor is now 13.5px and the readable body/request/command
           lines sit at ~15-16px. The request line uses clamp() so it scales fluidly
           between phone and desktop instead of being stepped DOWN on mobile, per
           .kiro/steering/20-device-compat.md which favours clamp() over fixed sizes. */
        .wt-request{margin-bottom:10px;display:flex;gap:10px;color:#fff;font-size:clamp(16px,1.1vw + 14px,18px);line-height:1.7}
        .wt-caret{color:#d1f470}
        /* THE ILLUSTRATIVE-TRACE CAPTION. A muted line directly under the intro, smaller and
           dimmer than .wt-request so it reads as a subordinate caption rather than a second
           headline. 12.5px, white at .62 -> ~13.4:1 on #000, comfortably past AA while still
           reading as secondary. The margin-bottom here carries the gap the intro line used to
           own (it was 32px on .wt-request), so the stream still starts a clear beat below. */
        .wt-caption{margin-bottom:28px;color:rgba(255,255,255,.62);font-size:12.5px;line-height:1.5}

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
           Each step IS a named service (gateway, auth, contacts, commerce, payments, ai,
           messaging, automation, queue, platform), so a hue that identifies the service is the
           same use the rotating hero pill puts this palette to: one colour per subject.

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
           ten rows now - see the note beside .wt-tick. Corrected rather than deleted because
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
           still wrong. Step 09 reads "FAILURE RECOVERED" - the whole point of that line is that
           the failure was absorbed - so a red dot on it would read as an unresolved alarm about
           the thing that was just resolved. Five hues cycle across the ten steps instead,
           ordered so no two adjacent steps repeat (1 blue, 2 purple, 3 amber, 4 lime, 5 green,
           6 blue, 7 amber, 8 purple, 9 lime, 10 green), and step 10 "EXECUTION VERIFIED" lands
           on green because that is the one hue whose convention matches its sentence. */
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
           visibly broken only because step 10, the single complete step, happens to be green.
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
        .wt-step:nth-child(8){--rgb:152,73,232;--ink:#9f56ea}
        .wt-step:nth-child(9){--rgb:209,244,112}
        .wt-step:nth-child(10){--rgb:61,163,90}

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
           It was lime on all rows, with the reasoning that "giving it five colours would
           turn a label into a legend the reader is expected to decode". Owner overruled it,
           three times, and on reflection the objection was answering the wrong question.
           This pill contains the service's own name - gateway, auth, contacts - so it IS the
           service identity, which is precisely what the dot hue encodes. Lime on every row meant the
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
        /* Service pills (gateway / auth / contacts / messaging ...). These were the smallest
           glyphs in the panel at 12.5px and read as "less" next to the enlarged rows, so they
           go to 13.5px - still a compact badge below .wt-name and .wt-desc, now legible. The
           hue note above is unchanged: colour lives on the pill fill/border, the text stays
           solid white at maximum contrast.
           BADGE-WEIGHT EVEN-OUT: fill .20 -> .26, border .60 -> .70 (applied uniformly, still
           keyed off the step's own var(--rgb) - deliberately NOT special-cased per hue, which
           would be fragile). On the pure #000 panel a .20 fill of the two low-luminance inks
           (blue 37,99,235 and purple 152,73,232) composited very dark and the pill read as a
           faint badge, while the lime/amber pills read strong - inconsistent weight across the
           ten steps. The small uniform alpha lift makes the fill/border read as a badge of
           consistent weight across all five hues without inventing any new colour and without
           touching the white label (kept #fff for max contrast - the text was never the issue).
           Kept modest on purpose so the pill stays a subtle badge below the step name, not a
           loud chip that competes with .wt-name. */
        .wt-svc{padding:2px 7px;border-radius:4px;background:rgba(var(--rgb),.26);border:1px solid rgba(var(--rgb),.70);color:#fff;font-size:13.5px;letter-spacing:.02em}
        /* .wt-name is the per-step heading (the step title, e.g. "Request accepted").
           SIZED 16px/600, back to the pre-#904 value. #904 bumped it 16px -> 18px, but the
           owner reported the heading "looks very big, not matching with the site": at 18px it
           read as a full section heading rather than a step label, out of keeping with the
           site's restrained scale (public card titles 22px/700, body 20px, while this dark mock
           panel deliberately runs its own smaller compact scale). It still stays the LARGEST
           glyph in the prose hierarchy - 16px sits above .wt-desc 15.5px and .wt-lane-name 15px
           (the monospace .wt-cmd code line is now also 16px, but it is a bordered code box in a
           different font-family, not a competing heading - see the .wt-cmd note below) -
           and its 600 weight plus solid white keeps a clear step down to the muted .74 sub-line,
           so the heading/subtext hierarchy restored in commit 57ef2daa is preserved. Colour
           stays #fff (21:1 on the #000 panel). .wt-head keeps min-height:20px + align-items:
           center, so the step dot alignment is unaffected by the smaller heading. */
        .wt-name{color:#fff;font-size:16px;font-weight:600}
        /* THE TICK TAKES THE STEP'S OWN HUE. THE NAME STAYS WHITE ON ALL EIGHT ROWS.
           Both the name and the tick were #d1f470 while the dots were lime too, so the row
           agreed with itself. Once the dots became one hue per service, lime here was the last
           thing in the panel still claiming the old meaning - and measured, only ONE row was
           affected, because the rule is gated on step.complete and the last step (now step 10,
           EXECUTION VERIFIED) is the only step whose data sets it. Names were #fff on every
           earlier step and lime on the complete step alone. That is why the recolour was
           reported as "not showing": it moved a single line from lime to green, two greens,
           while all the .wt-svc pills stayed lime. "The text is still lime" was three separate
           things - this name, this tick, and the pill - and the pill was the one the report was
           actually looking at.

           THE PILL IS NOW IN THE SAME SCHEME - see the note on .wt-svc. It used to be excluded
           and held lime on every row, which meant this rule recoloured exactly ONE line in the
           whole panel (the one step whose data says complete:true) while the pills stayed lime.
           That is why the change was reported as "not showing" after it shipped correct: it was
           a single row moving from lime to green, two greens, against unchanged lime chips.

           THE NAME IS NO LONGER IN THIS RULE. Owner picked option A from docs/step-review.md
           after seeing all five panels rendered, and the deciding argument only became visible
           once they were pictures rather than contrast figures:

           ON A SENTENCE, A HUE STOPS READING AS AN IDENTIFIER AND STARTS READING AS A SEVERITY.
           Colouring every name put the recovery step ("FAILURE RECOVERED") on a hue that reads
           as a warning badge, when the entire point of that line is that the failure was
           absorbed and needed no attention. That is the same reasoning already recorded above
           for EXCLUDING RED from the dot palette, and it applies with more force to a full
           sentence than to a 12px dot.

           The pill does not have the problem and the distinction is worth stating: a chip
           containing the single word "queue" is self-evidently an identifier and cannot be
           mistaken for a severity, because it is not a claim about anything. The sentence beside
           it can be. So hue lives on the dot and the chip - two labels - and never on prose.

           WHAT THIS BUYS. Every name holds #fff at 21:1, the most readable text on the panel,
           and the complete step stops being the one visibly dim row: it used to be the ONLY name
           that left white, which is why recolouring it read as a defect rather than as a signal.
           "Complete" is still carried three ways without colour - the tick below, the dot going
           static instead of pulsing, and the footer's "running"/"complete" wording - so WCAG
           1.4.1 stays unengaged and nothing that colour was uniquely saying has been lost.

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
        /* RAISED TO .66, on owner instruction that the panel's faint text was "not visible".
           This was .46 (4.58:1) - a bare pass on paper that read as nearly invisible on #000
           in practice, which is exactly what the owner reported. At .66 it measures ~7.6:1,
           comfortably clear of AA. The hierarchy it was protecting still holds: the timestamp
           stays dimmer than .wt-infra, which also came up (see below), and dimmer than .wt-desc.
           flowprobe.js asserts the measured ratios and cannot run in this sandbox (no headless
           browser); re-run it on a machine with playwright to refresh the recorded numbers. */
        .wt-time{color:rgba(255,255,255,.66);font-size:13.5px}
        /* .wt-desc is the primary step prose. It was .82 (~16:1), but at that alpha it sat so
           close to the solid-white .wt-name heading above it that the heading and its sub-line
           read as the same white, with no hierarchy - the owner reported "heading also white and
           subtext also white". Dropped to .74 (~9:1) so it stays clearly a muted sub-line BELOW
           the #fff name while remaining well clear of AA 4.5:1 on #000. Size stays 15.5px. */
        .wt-desc{max-width:780px;margin:7px 0 0;color:rgba(255,255,255,.74);font-size:15.5px;line-height:1.65}

        /* THE INLINE AI DECISION. The "ai >" tag is the one place lime is spent in the panel
           body as a thread marker - the same emphasis .wt-chip.is-ok puts lime to - so a reader
           scanning the stream can pick out where intelligence acted. The decision TEXT stays
           white at .82 (~16:1 on #000) so it reads as a legible sentence rather than an accent;
           lime is deliberately reserved for the tag and not spent on descriptive prose. */
        .wt-ai{margin-top:9px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;line-height:1.55}
        .wt-ai-tag{flex:0 0 auto;color:#d1f470;font-size:13px;font-weight:600;letter-spacing:.04em}
        .wt-ai-text{color:rgba(255,255,255,.82);font-size:14px}

        /* THE MICRO-TRACE. A small indented muted monospace block that reads as a detail under
           the step - the draft provenance on step 06, the retry sequence on step 09. White at
           .70 (~8:1 on #000), 13px, with a faint lime rule on the inline-start edge so it reads
           as nested under its step rather than as a sibling line. */
        .wt-subtrace{margin-top:9px;padding-left:12px;border-left:1px solid rgba(209,244,112,.30);display:grid;gap:4px}
        .wt-subtrace-line{color:rgba(255,255,255,.70);font-size:13px;line-height:1.5}

        /* .wt-cmd is the monospace command line (e.g. "$ contacts.get(...)") - the words
           auth / gateway / contacts live INSIDE this line, as .wt-fn / .wt-key / .wt-str spans
           that only set colour and inherit the size from here. RAISED 15px -> 16px: the owner
           kept reporting the "auth gateway in the code still small" because prior type-scale
           passes resized the headings and prose but never this command line, so it stayed a rung
           below. At 16px it now equals the step heading .wt-name (16px) and sits just above the
           description .wt-desc (15.5px). Heading and command line sharing 16px does not collapse
           the hierarchy: one is a 600-weight prose heading, the other a monospace code line in a
           bordered rgba box, so they stay visually distinct by shape and font-family. Everything
           else here (padding, rgba(255,255,255,.04) fill, border, radius, line-height, nowrap +
           overflow-x scroll) is unchanged; the child span colours are unchanged. */
        .wt-cmd{margin-top:11px;padding:12px 14px;overflow-x:auto;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.14);border-radius:7px;color:#fff;font-size:16px;line-height:1.7;white-space:nowrap}
        .wt-sh{margin-right:7px;color:rgba(255,255,255,.66)}
        .wt-fn{color:#d1f470}
        .wt-str{color:rgba(255,255,255,.80)}
        .wt-key{color:rgba(255,255,255,.68)}
        .wt-num{color:#d1f470}
        .wt-cm{color:rgba(255,255,255,.66)}

        /* The infra comment. Dim on purpose - it is the substrate, not the event - but
           still at the panel's unified 13.5px small-text floor because it carries the actual
           message. This line sits at font-size:13.5px now (it was reasoned about at smaller
           sizes in earlier passes, but the unified floor move raised it to 13.5px).
           THE ALPHA HISTORY IS WORTH KEEPING. This line is the one that makes the section's
           argument - "# dynamodb · single-table · on-demand capacity", the shared foundation
           named under every step - and at a much lower alpha (rgba(255,255,255,.44)) it had
           composited to roughly 4.25:1 on #000, which reasons out as below the 4.5:1 WCAG
           1.4.3 asks for body text. It was the only one of the panel's text styles that read
           as a bare pass, so it was lifted. Deliberately NOT .62: that is near .wt-desc's
           territory, and this line must stay dimmer than the description it sits under, which
           is the whole point of the "dim on purpose" above. RAISED TO .70 on the same owner
           instruction that lifted the other faint lines: this is the line that carries the
           section's argument, so it has to be solidly legible, not a bare pass. .70 on #000
           reasons out to roughly ~8:1 (approximate - see the probe note below) and still sits
           BELOW .wt-desc's .74, so the "dim on purpose, but above the floor" order the comment
           describes is preserved, now at the 13.5px floor.
           Re-measure with: node tools/browser/flowprobe.js - it asserts every ratio here, and
           cannot run in this sandbox (no headless browser), so the ratios above are reasoned,
           not re-measured; refresh them on a machine with one.
           (No backticks in this comment: this sits inside a style jsx template literal, where
           one stray backtick ends the literal and the build fails at type-check.) */
        .wt-infra{margin-top:9px;color:rgba(255,255,255,.70);font-size:13.5px;line-height:1.6}

        .wt-results{margin-top:11px;display:flex;flex-wrap:wrap;gap:7px}
        .wt-chip{padding:5px 9px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.14);border-radius:5px;color:rgba(255,255,255,.74);font-size:13.5px}
        .wt-chip.is-ok{color:#d1f470;border-color:rgba(209,244,112,.34)}
        /* A warning is carried by weight, not by a second hue: brighter text on a
           brighter border, still neutral, so lime stays the only accent in the panel body. */
        .wt-chip.is-warn{color:rgba(255,255,255,.92);border-color:rgba(255,255,255,.38)}

        /* CONCURRENCY, SHOWN AS COLUMNS. auto-fit rather than a fixed count so the lanes
           wrap cleanly instead of overflowing - they still read as simultaneous, which a
           horizontal scrollbar would destroy.
           FIVE CHANNELS NOW (whatsapp / rcs / sms / email / voice), where it was four - RCS was
           added. The min dropped 132px -> 108px so five lanes balance across the measure without
           a horizontal scrollbar. Reasoned at the breakpoints (the panel's inner width is the
           viewport minus the page gutters and the panel's own 34px/18px side padding; browser
           probes cannot run here so this is by arithmetic):
             320px  phone: inner ~= 248px -> floor(248/108) = 2 per row, 3 rows, no overflow.
             375px  phone: inner ~= 303px -> 2 per row (108*3 = 324 > 303), 3 rows, no overflow.
             768px  single-column band, panel full width: inner ~= 650px+ -> 5 fit (108*5 = 540),
                    so all five sit on one row with room to spare.
             1024px two-column collapses to one here, panel full width -> 5 across comfortably.
             1440px two-column, panel is the 1fr left column (~800px+): 5 across easily.
           auto-fit means no row ever exceeds the track count that fits, so there is never a
           horizontal scroll; the worst case is 2-per-row on the narrowest phone, which still
           reads as parallel tracks. */
        .wt-lanes{margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(108px,1fr));gap:8px}
        .wt-lane{padding:9px 10px;background:rgba(255,255,255,.04);border:1px solid rgba(209,244,112,.22);border-radius:6px;display:flex;flex-direction:column;gap:3px}
        /* A short lime rule at the top of each lane, so the five read as parallel tracks
           starting together rather than as five unrelated cards. */
        .wt-lane-bar{display:block;width:22px;height:2px;border-radius:2px;background:#d1f470;margin-bottom:3px}
        /* The lane header: a CSS-drawn status dot beside the channel name. The dot is NOT a
           glyph - several of this site's fonts have no symbol coverage, so a literal circle
           would render as tofu somewhere, the same trap the tick and the window lights avoid. */
        .wt-lane-head{display:flex;align-items:center;gap:7px}
        /* STATUS, CSS-DRAWN. A used channel takes the green third-light value #3da35a (6.58:1
           on #000, the same hue the chrome state dot uses for "healthy"); an available-but-not-
           selected channel (voice) takes a hollow, dimmed white dot - a ring at .30 alpha with
           no fill - so "not selected" reads as off/muted without introducing a new colour. */
        .wt-lane-dot{width:7px;height:7px;flex:0 0 auto;border-radius:50%}
        .wt-lane-dot.is-on{background:#3da35a}
        .wt-lane-dot.is-off{background:transparent;border:1px solid rgba(255,255,255,.30)}
        /* FIVE-CHANNEL lanes (whatsapp / rcs / sms / email / voice) were the smallest body text
           left after the earlier size passes, so they still read as "less" than the rest of the
           panel. Lane-name goes 13.5px->15px and lane-detail 13px->14px, staying under .wt-desc's
           15.5px and keeping label >= detail. Lane-detail opacity is .74 - lifted from the old
           faint .70 for legibility (~9:1 on #000, well past AA) but deliberately held as a muted
           white BELOW the solid-white lane-name so the label and its sub-line keep a clear
           hierarchy rather than both reading as plain white. No new hex: palette unchanged. */
        .wt-lane-name{color:#fff;font-size:15px;font-weight:600}
        .wt-lane-detail{color:rgba(255,255,255,.74);font-size:14px;line-height:1.45}

        .wt-checks{margin-top:11px;display:grid;gap:8px}
        .wt-check{display:flex;align-items:center;gap:8px;color:rgba(255,255,255,.74);font-size:13.5px}
        .wt-check-tick{color:#d1f470}

        /* Fades the stream out under the footer rather than letting rows collide with
           it. The gradient has to end in the panel's own #000 or it shows a seam.
           FOOTER STATUS LEGIBILITY (user: the footer "N / 10" status read the same faint grey
           as the chrome title and blended in): color raised .70 -> .86 by OPACITY ONLY, so the
           footer state line (left running/complete and right-side .wt-foot-right "N / 10
           services", which inherits this colour) reads as deliberate, legible chrome rather than
           near-invisible. Still a muted white BELOW the solid-#fff step content, size unchanged
           at the 13.5px small-text floor. .86 on #000 is ~17:1, well past AA.
           THE DONE STATE IS ONE LONG LINE, not a left/right split. Running shows the lime dot +
           "running" on the left and the live "N / 10 services" counter on the right. Done
           replaces both with a single CSS-tick + "EXECUTION COMPLETE - 10 / 10 services ..."
           line; the row height grows to fit it and the text is allowed to wrap on a narrow
           panel (the min-height floor keeps the chrome bar shape when it is one line). */
        .wt-foot{flex:0 0 auto;min-height:50px;padding:9px 24px;display:flex;align-items:center;background:#000;border-top:1px solid rgba(209,244,112,.30);color:rgba(255,255,255,.86);font-size:13.5px}
        .wt-foot-left{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
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
          /* HEIGHT: same intent as .home-shell and .nav-menu - size to what the visitor can
             actually see, not to the viewport with the chrome hidden. It was a min() of 560px
             and a raw-vh calc that subtracted 180 pixels: 100vh overstates the phone viewport
             while the address bar is showing, so the panel grew taller than the screen and
             jumped as the chrome collapsed, and that subtrahend matched no element in the layout.
             The ceiling stays at 560px so the panel never dominates a tall phone. The vh term
             is the fallback and is declared first; dvh is declared second and tracks the
             visible viewport, so a browser without dvh keeps the vh value. 100dvh never
             overflows the visible area, so the min() ceiling is the only cap that binds in
             practice. */
          .wt-window{height:min(560px,100vh);height:min(560px,100dvh);border-radius:12px}
          .wt-space{padding:23px 18px 60px}
          .wt-bar-state{display:none}
          .wt-step{padding-left:29px}
          /* THE MOBILE DOWN-SIZE IS GONE, on owner instruction. This rule used to drop the
             request line to 12px - SMALLER than its 15px desktop value - which was the opposite
             of what a phone reader needs and the exact complaint that was reported. The line now
             keeps its fluid clamp() size on mobile, so the panel is never smaller on a phone
             than on a laptop. */
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
