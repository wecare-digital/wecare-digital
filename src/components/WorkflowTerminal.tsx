import React, { useEffect, useRef, useState } from 'react';

/**
 * Animated workflow terminal, from the owner's HTML mock, restyled onto the site.
 *
 * SELF-STYLING, like BrandBadge and RotatingHero: styled-jsx cannot scope a composite
 * component from its parent, so this owns every rule it needs and the consumer owns
 * nothing but placement.
 *
 * PURE CODE, NOT PROSE. The panel used to pair a two-tier status label (service pill +
 * "REQUEST ACCEPTED" heading) with a plain-English description sentence under each step.
 * On owner instruction the panel now renders as what it claims to be: a MACHINE EXECUTION
 * LOG. Each step is a block of monospace lines typed the way real tooling types them -
 * a "$" call, a "->" return, a "#" note, a "!" error, a checkmark rollup, an "ai >"
 * decision thread, and a ">" substep. There is no prose description and no status-label
 * header any more; the service name and the timing live on the call line itself. The
 * trace is honest about what it is - it is still aria-hidden with a static summary and
 * carries no benchmark claim.
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

/**
 * THE LINE MODEL. Each step is an ordered list of typed lines, and the type drives both
 * the glyph prefix and the colour. Keeping the content as data (not JSX) lets the whole
 * step block stay inline in the ONE map in the return tree, which is the styled-jsx
 * scoping invariant: a rule only applies to an element statically present in this
 * component's return tree, so extracting the line rendering into a helper or child
 * component would silently drop every .wt-line rule. The map therefore switches on
 * line.type inline and never delegates.
 *
 *   '$'      a service CALL. The prompt is muted; the call text is solid white. The step
 *            TIME is right-aligned on this line on desktop and stacks under it on mobile.
 *   '->'     a RETURN value. Readable white (.82).
 *   '#'      a NOTE / comment. Muted white (.70).
 *   '!'      an ERROR. Red #dc2626 (step 17, queue, only).
 *   'tick'   a verification ROLLUP (step 21, platform). Lime ticks before each item.
 *   'ai'     an "ai >" DECISION. The "ai >" tag is lime; the decision text is readable
 *            white (.82). Exactly nine steps carry one - 4,7,8,9,11,12,13,15,21 (contacts,
 *            media, commerce, payments, attribution, kb, ai, messaging, platform).
 *   '>'      a SUBSTEP (step 13, ai, compose). Muted-ish white.
 *   'lanes'  the nested 5-channel dispatch box (step 15, messaging, only).
 */
type LineType = '$' | '->' | '#' | '!' | 'tick' | 'ai' | '>' | 'lanes';
type Lane = { name: string; detail: string; on?: boolean };
interface Line {
  type: LineType;
  /** The line text for every type except 'lanes' / 'tick'. */
  text?: string;
  /** The verification items for a 'tick' rollup line. */
  ticks?: string[];
  /** The channel lanes for the 'lanes' box. */
  lanes?: Lane[];
}

interface Step {
  /** The service that did the work, shown in the call-line pill and the hue rail. */
  service: string;
  /** The cumulative ELAPSED time at this step - a monotonically non-decreasing running
   *  clock across the 21 steps ending at ~2.1s, not a per-step duration - right-aligned on
   *  the "$" call line (stacked under it on mobile). */
  time: string;
  /** The ordered code/log lines that make up this step. */
  lines: Line[];
  /** The final verification step carries this so the dot/rail read as the closing beat. */
  complete?: boolean;
}

/**
 * WHAT THIS PANEL SAYS ABOUT THE COMPANY, which is the whole reason it was rewritten AGAIN.
 *
 * THIS IS A 21-SERVICE AI-EXECUTION TRACE that shows AI AT EVERY DECISION, rendered as a
 * machine log rather than a labelled plan (recorded learning 75c80121-7ead-4c49-b900-
 * a0817515f2db set the AI-at-every-decision framing; this pass makes the surface pure
 * code). The stream shows one order (#WD-4821) executing end to end across twenty-one
 * services - inbound, gateway, auth, contacts, crm, catalog, media, commerce, payments,
 * whatsapp (wa.pay), attribution, kb, ai, shortener, messaging, automation, queue, analytics,
 * sla, whatsapp (wa.order_status), platform.
 * It opens where a real order opens: a WhatsApp message arrives (inbound), and the note
 * on that step is honest - WhatsApp is the conversation surface, the website is where the
 * payment happens. At each step that involves a judgement the panel names the AI decision
 * inline with a lime "ai >" marker: the intent is read, the product image is selected, the
 * request is validated, the transaction is risk-checked, the order is credited to the
 * campaign that drove it, the reply is grounded in retrieved sources and drafted from
 * evidence, channels are selected, and the whole run is verified against one model. AI
 * understands and decides; the platform executes.
 *
 * NINE STEPS CARRY AN ai DECISION (4,7,8,9,11,12,13,15,21 - contacts, media, commerce,
 * payments, attribution, kb, ai, messaging, platform), which is the "AI at 9 decisions"
 * the done footer reports. The two WhatsApp beats inserted at step 10 (wa.pay, native
 * in-chat payment offered) and step 20 (wa.order_status, status pushed outside the 24h
 * window) carry NO ai marker - they are surface mechanics, not judgements, so the count
 * stays nine. The remaining steps are platform mechanics - inbound receiving
 * a message, a gateway accepting a request, auth verifying access, a CRM write, a catalog
 * read, a link being shortened, an automation rule, a queue recovering a failed send,
 * analytics tracking an outcome, an SLA check - and they carry no ai marker on purpose.
 * Those are resilience and plumbing, not intelligence, and claiming AI there would be the
 * kind of overreach the panel is careful to avoid.
 *
 * THE CODE LINES CARRY THE DETAIL. Step 12 (kb) retrieves the sources the reply is grounded
 * in; step 13 (ai) composes the draft from them; step 15 (messaging) nests the five-channel
 * dispatch box under the dispatch call; step 17 (queue) shows the retry recovering a failed
 * send; step 21 (platform) rolls up the verification ticks. The five lanes in the messaging
 * step show the channel OPTIONS evaluated at once - a vertical list would have read as five
 * more sequential steps, which is precisely the wrong impression.
 *
 * Nothing here claims a benchmark. The time on each call line reads as CUMULATIVE ELAPSED
 * time in one trace - a running clock that only ever goes up, from 4ms at inbound to
 * ~2.1s at the final verify - rather than an isolated per-step duration, so the numbers add
 * up as one timeline to a reader who reads them in sequence. They are still illustrative,
 * the panel is aria-hidden with a static summary that says so, so no assistive technology is
 * told these are measurements.
 */
const STEPS: Step[] = [
  {
    service: 'inbound', time: '4ms',
    lines: [
      { type: '$', text: 'inbound.receive  wa_msg  from=+9199••••1121' },
      { type: '->', text: 'text="where\'s my order?"  media=0' },
      { type: '#', text: 'whatsapp is the surface · website is checkout' },
    ],
  },
  {
    service: 'gateway', time: '12ms',
    lines: [
      { type: '$', text: 'gateway.accept  POST /v1/orders  ·  tls=1.3  ·  ap-south-1' },
      { type: '->', text: '200  order=#WD-4821  routed=commerce' },
      { type: '#', text: 'single hop · terminated at edge' },
    ],
  },
  {
    service: 'auth', time: '43ms',
    lines: [
      { type: '$', text: 'auth.verify(token)' },
      { type: '->', text: 'ok  subject=cust_2841  tenant=acct_2841' },
      { type: '#', text: "scoped token · can't reach past grant" },
    ],
  },
  {
    service: 'contacts', time: '61ms',
    lines: [
      { type: '$', text: 'contacts.get("cust_2841")' },
      { type: '->', text: '1 read  consent=[whatsapp,rcs,sms,email]  voice=off' },
      { type: 'ai', text: 'intent("where\'s my order?") -> order_status' },
    ],
  },
  {
    service: 'crm', time: '74ms',
    lines: [
      { type: '$', text: 'crm.log(interaction, cust_2841)' },
      { type: '->', text: 'thread=th_8841  linked=order #WD-4821' },
      { type: '#', text: 'one customer record · every touch on it' },
    ],
  },
  {
    service: 'catalog', time: '83ms',
    lines: [
      { type: '$', text: 'catalog.resolve(sku=WD-TEE-01)' },
      { type: '->', text: 'in_stock  price=₹499  meta_sync=ok' },
      { type: '#', text: 'catalog: single source · meta-synced' },
    ],
  },
  {
    service: 'media', time: '101ms',
    lines: [
      { type: '$', text: 'media.render(sku=WD-TEE-01)' },
      { type: '->', text: 'asset=img_4471  variant=card  cached' },
      { type: 'ai', text: 'image selected to match the request' },
    ],
  },
  {
    service: 'commerce', time: '137ms',
    lines: [
      { type: '$', text: 'order.commit(#WD-4821)  { items: 1 }' },
      { type: '->', text: 'ok  stock −1  state=confirmed' },
      { type: 'ai', text: 'request validated against order' },
    ],
  },
  {
    service: 'payments', time: '377ms',
    lines: [
      { type: '$', text: 'payments.capture(#WD-4821)  gateway=razorpay' },
      { type: '->', text: 'paid  invoice=#INV-4821' },
      { type: 'ai', text: 'risk_score=0.03 -> clear' },
    ],
  },
  {
    service: 'whatsapp', time: '384ms',
    lines: [
      { type: '$', text: 'wa.pay(#WD-4821)  in_chat' },
      { type: '->', text: 'offered  provider=razorpay  config=active' },
      { type: '#', text: 'native payment · live config · invoice/service path' },
    ],
  },
  {
    service: 'attribution', time: '391ms',
    lines: [
      { type: '$', text: 'attribution.link(#WD-4821)' },
      { type: '->', text: 'source=meta_ads  campaign=cat_4471  click=2h ago' },
      { type: 'ai', text: 'order credited to the ad that drove it' },
    ],
  },
  {
    service: 'kb', time: '512ms',
    lines: [
      { type: '$', text: 'kb.query(intent=order_status)' },
      { type: '->', text: '2 sources  top=shipping_policy' },
      { type: 'ai', text: 'grounded in retrieved sources' },
    ],
  },
  {
    service: 'ai', time: '811ms',
    lines: [
      { type: '$', text: 'ai.generate(intent=order_status, ctx=#WD-4821)' },
      { type: '>', text: 'compose    -> grounded draft' },
      { type: '->', text: 'draft_ready  tokens=214' },
      { type: 'ai', text: 'written from evidence, not a template' },
    ],
  },
  {
    service: 'shortener', time: '828ms',
    lines: [
      { type: '$', text: 'links.shorten(order_url)' },
      { type: '->', text: 'wec.ar/o/4821  tracked' },
      { type: '#', text: 'one short link · attribution preserved' },
    ],
  },
  {
    service: 'messaging', time: '857ms',
    lines: [
      { type: '$', text: 'messaging.dispatch(draft, channels=5)' },
      { type: 'ai', text: 'selected the channels this customer actually uses' },
      { type: 'lanes', lanes: [
        { name: 'whatsapp', detail: 'delivered · pay-link', on: true },
        { name: 'rcs', detail: 'available · not selected', on: true },
        { name: 'sms', detail: 'sent', on: true },
        { name: 'email', detail: 'sent', on: true },
        { name: 'voice', detail: 'skipped · not eligible', on: false },
      ] },
      { type: '->', text: '3 sent · 1 delivered · parallel · each tracked' },
      { type: '#', text: 'link over whatsapp · pay on site' },
    ],
  },
  {
    service: 'automation', time: '868ms',
    lines: [
      { type: '$', text: 'rules.eval(order=#WD-4821)' },
      { type: '->', text: '1 matched: "post-purchase follow-up"' },
      { type: '#', text: 'follow-up warranted -> scheduled +24h' },
    ],
  },
  {
    service: 'queue', time: '2.07s',
    lines: [
      { type: '$', text: 'queue.worker <- email.send' },
      { type: '!', text: '503 provider_unavailable' },
      { type: '->', text: 'backoff 400ms · retry 2/5 · accepted' },
      { type: '#', text: 'idempotent · delivered once · 0 dropped' },
    ],
  },
  {
    service: 'analytics', time: '2.08s',
    lines: [
      { type: '$', text: 'analytics.track(delivery)' },
      { type: '->', text: 'opened=whatsapp  ctr=logged' },
      { type: '#', text: 'outcomes flow back to attribution' },
    ],
  },
  {
    service: 'sla', time: '2.09s',
    lines: [
      { type: '$', text: 'sla.track(#WD-4821)' },
      { type: '->', text: 'first_response 46ms  target 5m  ·  within SLA' },
      { type: '#', text: 'sla: measured, not assumed' },
    ],
  },
  {
    service: 'whatsapp', time: '2.1s',
    lines: [
      { type: '$', text: 'wa.order_status(#WD-4821)' },
      { type: '->', text: 'processing -> shipped' },
      { type: '#', text: 'status in-chat · outside the 24h window' },
    ],
  },
  {
    service: 'platform', time: '2.1s', complete: true,
    lines: [
      { type: '$', text: 'trace.verify(#WD-4821)' },
      { type: 'tick', ticks: [
        'inbound', 'order', 'payment', 'catalog', 'media',
        'crm', 'attribution', 'kb', 'ai', 'channels', 'wa pay', 'status', 'sla',
      ] },
      { type: '->', text: '21/21 services · one identity · one trace · one foundation' },
      { type: 'ai', text: 'one model across all of it' },
    ],
  },
];

// Per-step dwell: richer steps hold longer so there is time to read them. Keyed off what
// the step CONTAINS - how many lines, whether it carries the lane box, a rollup or substeps -
// rather than its index, so reordering STEPS does not silently retime the sequence. The lane
// step, the verification rollup and the multi-line ai/queue steps hold longest (>=900ms so
// they stay readable), the plain three-line calls are quickest. The two WhatsApp beats added
// at steps 10 and 20 are plain three-line calls, so each dwells 750ms. A full 21-step pass
// runs roughly 23s of stepping (17900ms of dwell plus the 250ms inter-step gap per step)
// plus the 1500ms inter-loop hold; the richest steps stay above 900ms so nothing flashes past.
const dwell = ( step: Step ): number => {
  if ( step.lines.some( l => l.type === 'lanes' ) ) return 1200;
  if ( step.complete || step.lines.some( l => l.type === 'tick' ) ) return 1150;
  if ( step.lines.some( l => l.type === '>' ) ) return 1050;
  if ( step.lines.some( l => l.type === '!' ) ) return 1000;
  if ( step.lines.length >= 4 ) return 900;
  return 750;
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
   * HTML: a grep for the first step's content in out/index.html returned nothing, and with
   * JavaScript disabled the largest element on the home page was a black rectangle holding one
   * line of text and a footer reading "running 0 / 21". Every line of the twenty-one steps
   * existed only after hydration, so a no-JS reader, a WebView with scripting off, and anything
   * reading the HTML rather than running it all got an empty panel - on the same site that just
   * started publishing llms.txt and an /mcp endpoint for exactly those readers.
   *
   * Shipping the COMPLETE state fixes it with no new markup: twenty-one rows, all settled, footer
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
   * what re-enters the stepping effect for another pass. The loop runs CONTINUOUSLY until a
   * reader pauses it - there is no cap and no natural stop, so there is no `stopped` state and
   * no "Replay": the control reads Pause <-> Play only. */
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
   * repo already carries many of those and this file is not adding more. It cannot be hoisted
   * into a lazy useState initialiser either, because the branch reads browser-only globals
   * (matchMedia, visibilityState) that are undefined during the static export and would hydrate
   * to a different value than they render to. A timeout of 0 resolves both: the decision happens
   * after commit, on the client, one frame later than paint, which is invisible for an element
   * that already shows the finished panel.
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
  // The original reset to `shown: 0` and restarted, dropping the panel back to one line inside
  // a tall box every cycle.
  //
  //   1. WCAG 2.2.2. Content that moves automatically for more than five seconds must be
  //      pausable, stoppable or hideable. The original offered none of the three. Playing once
  //      was the conformant answer that needed no new control, which is why it was preferred
  //      at the time over adding a button.
  //   2. THE PANEL EMPTIED ITSELF. The reset dropped it back to one line inside a tall box -
  //      nearly empty - every cycle. So the largest element on the home page spent part of
  //      every cycle showing nothing, and anyone arriving mid-reset met a black rectangle.
  //
  // Owner asked for continuous play. BOTH DEFECTS ARE FIXED RATHER THAN RE-ACCEPTED:
  //   1. is answered by .wt-play, a real pause control rendered outside the aria-hidden window
  //      so it is exposed to assistive tech rather than focusable-but-invisible.
  //   2. is answered by never rewinding `shown`. Only `settled` rewinds, so all twenty-one rows
  //      stay mounted for the whole cycle and the panel is never empty at any moment.
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
   * panel, then rewind and replay, then loop. A visitor therefore reads a completed run first
   * and watches it replay - rather than seeing twenty-one settled rows blink back to running one
   * frame after hydration, which is what starting at 0 would have produced. */
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
        /* THE PASS IS DONE, SO HOLD THE FINISHED STATE BRIEFLY AND THEN LOOP. There is no cap:
         * the end-of-pass branch ALWAYS schedules a restart, so the only thing that stops the
         * motion is a reader pressing Pause (which tears this effect down before the restart
         * fires) or the tab going hidden. The never-empty invariant is preserved: `shown` was
         * never rewound, so all twenty-one rows remain mounted and settled - the exact frame of
         * the initial and reduced-motion render - during the hold. */
        /*
         * IT LOOPS AGAIN, ON OWNER INSTRUCTION - BUT NOT THE LOOP THAT WAS REMOVED.
         *
         * The old loop reset `shown` to 0, and that is the defect recorded above: the panel
         * dropped to a single line inside a tall box, nearly empty, every cycle, so the
         * largest element on the home page periodically showed nothing and anyone arriving
         * mid-reset met a black rectangle.
         *
         * THIS RESTART LEAVES `shown` AT STEPS.length AND ONLY REWINDS `settled`. All twenty-one
         * rows stay mounted and on screen for the entire cycle; what replays is the
         * running-to-done pass travelling down them. The panel is never empty at any point,
         * which is the whole objection answered rather than accepted.
         *
         * What a reader sees at the restart edge is the stack going live at once and then
         * settling row by row - a heartbeat rather than a rebuild. Stated because twenty-one dots
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
        /* THE INTER-LOOP HOLD. Trimmed from 3200ms to 1500ms now that the panel loops forever
         * rather than stopping after a capped run: a 3.2s dead pause between passes read as the
         * animation having finished, which is the wrong signal for a continuous loop. 1.5s is a
         * clear beat on the finished state - long enough to read the complete footer - without
         * the loop feeling stalled. */
        }, 1500 );
        return;
      }
      // Only the first pass reveals rows. Every later pass finds all twenty-one already mounted,
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
   *   1. Pause pressed during the 1.5s "complete" hold left `resumeRef` at STEPS.length, so
   *      Play re-entered the end branch: the panel then sat completely still for another 1.5s
   *      before anything moved. Pressing Play and watching nothing happen is indistinguishable
   *      from a broken button.
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
   * away from them. Steps are spaced over a second apart, so roughly one scroll in ten hit that
   * window, and because the cycle is deterministic a scroll at a fixed offset hit it EVERY time,
   * which is how both engines failed identically.
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
   * right for a stream that only ever grows, which is what pass one is. It is WRONG for a loop:
   * on every later pass the running-to-done frontier travels from the top while the box sits
   * pinned to the bottom, so the moving edge is off screen and the panel reads as a frozen
   * screenshot of its own last rows.
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
   * WHY NOT GROW THE PANEL SO NOTHING SCROLLS, which was the earlier alternative. Fitting the
   * whole content would make the panel several screens of black terminal tall on a phone and
   * balloon the page height; a fixed-height box that scrolls its own content is the smaller cost.
   *
   * THE READER STILL WINS WHILE THEY ARE READING. Their own scroll clears `followRef`, so the
   * rest of that pass leaves the view where they put it, which is what the original "stop
   * fighting a reader who scrolls back" note was protecting and it is still protected. Following
   * resumes at the next restart, stated plainly because it IS a yank: the cost of never resuming
   * is a reader who scrolls once and then watches a permanently still panel for as long as the
   * tab is open, which is the defect above with extra steps. It lands on the restart edge, where
   * the whole stack already pulses, so it coincides with a visual event that is there anyway
   * instead of introducing a new one.
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
   * same commit, and on that first commit the finished panel is static and the effect above
   * returns at its settled>=rows.length-1 guard before scrolling anything. There is no scroll
   * for this listener to miss. */
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
          screen reader should not receive twenty-one nodes appearing on timers. */}
      <p className="wt-sr">
        An illustration of one customer order moving through twenty-one of our services with
        AI at each decision: a WhatsApp message arrives on the conversation surface while the
        website remains where payment happens; the request is accepted at the edge; access is
        verified against one scoped identity; the customer context is loaded while AI reads the
        intent; the interaction is logged to the CRM against one customer record; the catalog
        item is resolved and synced so the app and Meta read the same record; a product image
        is generated by AI to match the request; the order is committed; payment is captured on
        the website; a native in-chat payment is also offered on the invoice/service path with
        live config, while the cart money flow stays the website Razorpay capture and WhatsApp
        remains the conversation and status surface; the order is attributed to the campaign
        that drove it; the knowledge base is queried and the reply is grounded in the retrieved
        sources; AI drafts the response from that evidence rather than a template; a tracked
        short link is generated; five channels are evaluated and the eligible ones deliver the
        reply with a pay-link in parallel; an automation rule fires a follow-up on its own; a
        failed send is retried and confirmed by the platform so nothing is dropped; engagement
        is tracked back to attribution; the service level is checked against its target; the
        order status is pushed to WhatsApp outside the 24-hour window; and finally all
        twenty-one services and the AI are verified on one shared foundation. The AI
        understands, decides and drafts while the platform executes, and the timings shown are
        illustrative rather than measured.
      </p>

      {/* dir="ltr" LOCKS THE TERMINAL, and it is a correctness fix rather than a preference.
          This panel draws literal machine output - a shell prompt, "platform · runtime",
          an "ai >" decision thread, "503 provider_unavailable". None of that is prose and
          none of it is left-to-right by convention: it is left-to-right by SYNTAX. With the
          document mirrored for an Arabic reader the flex rows inside reversed, so the window
          lights moved to the right, the prompt reversed, and the punctuation in the call
          reordered - a reader who knows the API would see code that no longer parses.
          Found by measuring mirror symmetry, not by looking: comparing each element's
          distance from the inline-start edge in ltr against rtl, this subtree was the largest
          asymmetry on the home page.
          It pairs with the aria-hidden already here. Both say the same thing about this
          panel - it is a picture of a machine, not text - so it is exempt from translation
          and from mirroring for one reason. */}
      {/* THE PAUSE CONTROL SITS OUTSIDE .wt-window ON PURPOSE, and the purpose is not layout.
          The window carries aria-hidden="true" because a screen reader should not receive
          twenty-one nodes appearing on timers - the static .wt-sr paragraph above is what it
          gets instead. A <button> placed inside that subtree would still be in the tab order
          while absent from the accessibility tree: reachable by keyboard, announced as nothing.
          So the control is a sibling and is positioned over the title bar with CSS.

          IT EXISTS BECAUSE THE LOOP EXISTS. WCAG 2.2.2 requires content that moves
          automatically for more than five seconds to be pausable, stoppable or hideable, and
          one cycle here runs well over ten seconds. This is the pause. It is the reason the
          panel is allowed to animate continuously at all, not a convenience bolted on afterwards.

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
          /* TWO LABELS, ONE CONTROL. Pause while playing, Play while paused - there is no
             "Replay" because the loop runs continuously and never stops on its own, so the
             control is only ever a toggle. The triangle mark is shown while paused (it starts
             motion); the running state shows the two pause bars. aria-pressed tracks `paused`. */
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
          <span className="wt-bar-title">platform · runtime</span>
          <span className="wt-bar-state"><i className="wt-state-dot" />live trace</span>
        </div>

        <div className="wt-space">
          <div className="wt-request"><span className="wt-caret">›</span><span>One request. Intelligence at every decision.</span></div>

          <div ref={ streamRef }>
            { visible.map( ( step, i ) => {
              const state = i <= settled ? 'is-done' : 'is-running';
              const last = i === STEPS.length - 1;
              return (
                /* KEY IS THE INDEX, NOT step.service. The service label is no longer unique:
                   both WhatsApp beats (wa.pay, wa.order_status) carry service: 'whatsapp', so
                   keying on the name would collide. The list is a fixed, ordered sequence that
                   is never reordered or filtered - only sliced from the front by `shown` - so
                   the positional index is a stable, correct key here. */
                <div key={ i } className={ `wt-step ${state} ${last ? 'is-last' : ''}`.trim() }>
                  <span className="wt-dot" />
                  {/* THE STEP'S CODE BLOCK. overflow-x:auto so an over-long line scrolls on its
                      OWN and never the page (.wt-space keeps overflow-x:hidden). ALL line
                      rendering stays inline in this map and switches on line.type - extracting
                      it into a helper or child component would silently drop every .wt-line
                      rule, because styled-jsx only scopes elements statically present in this
                      return tree. */}
                  <div className="wt-code">
                    { step.lines.map( ( line, j ) => {
                      if ( line.type === '$' ) {
                        return (
                          <div key={ j } className="wt-line wt-call">
                            <span className="wt-call-main">
                              <span className="wt-prompt">$</span>
                              <span className="wt-call-text">{ line.text }</span>
                            </span>
                            <span className="wt-time">{ step.time }</span>
                          </div>
                        );
                      }
                      if ( line.type === '->' ) {
                        return (
                          <div key={ j } className="wt-line wt-return">
                            <span className="wt-glyph">-&gt;</span>
                            <span className="wt-line-text">{ line.text }</span>
                          </div>
                        );
                      }
                      if ( line.type === '#' ) {
                        return (
                          <div key={ j } className="wt-line wt-note">
                            <span className="wt-glyph"># </span>
                            <span className="wt-line-text">{ line.text }</span>
                          </div>
                        );
                      }
                      if ( line.type === '!' ) {
                        return (
                          <div key={ j } className="wt-line wt-error">
                            <span className="wt-glyph">!</span>
                            <span className="wt-line-text">{ line.text }</span>
                          </div>
                        );
                      }
                      if ( line.type === '>' ) {
                        return (
                          <div key={ j } className="wt-line wt-sub">
                            <span className="wt-glyph">&gt;</span>
                            <span className="wt-line-text">{ line.text }</span>
                          </div>
                        );
                      }
                      if ( line.type === 'ai' ) {
                        /* THE INLINE AI DECISION. The "ai >" tag is the one place lime is spent
                           in the panel body as a thread marker; the decision TEXT stays readable
                           white (.82) so it reads as a sentence, not an accent. */
                        return (
                          <div key={ j } className="wt-line wt-ai">
                            <span className="wt-ai-tag">ai ▸</span>
                            <span className="wt-ai-text">{ line.text }</span>
                          </div>
                        );
                      }
                      if ( line.type === 'tick' ) {
                        /* THE VERIFICATION ROLLUP (step 21, platform). Lime ticks before each
                           verified service, wrapping inline. CSS-drawn checkmark would be ideal but the
                           tick glyph is already used elsewhere in the panel and renders here. */
                        return (
                          <div key={ j } className="wt-line wt-rollup">
                            { line.ticks?.map( t => (
                              <span key={ t } className="wt-rollup-item">
                                <span className="wt-rollup-tick">✓</span>{ t }
                              </span>
                            ) ) }
                          </div>
                        );
                      }
                      if ( line.type === 'lanes' ) {
                        /* THE NESTED 5-CHANNEL BOX (step 15, messaging, only). Parallel lanes, side by side
                           on purpose - stacked they would read as five more sequential steps,
                           the opposite of the point. auto-fit minmax grid so they wrap cleanly
                           with no whole-page horizontal scroll at 320/375/768/1024/1440. Each
                           lane carries a CSS-drawn status dot: green #3da35a when selected, a
                           hollow white ring when available-but-not (voice). NO emoji. */
                        return (
                          <div key={ j } className="wt-lanes">
                            { line.lanes?.map( lane => (
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
                        );
                      }
                      return null;
                    } ) }
                  </div>
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
            of the steps. As a flex sibling of the scroll area it is pinned to the window
            for free. */}
        {/* THE COUNT LIVES ONLY HERE, AND IT IS LIVE. The chrome bar carries no count, so this
            is the one place the panel reports progress. Running: the lime dot + "running" and a
            live "N / 21" counter where N is the count of SETTLED rows, not `shown`. `shown` is
            pinned at STEPS.length by the never-empty invariant (it starts at 21 and never
            rewinds so all twenty-one rows stay mounted), so it cannot report progress - it would
            read 21 / 21 for the whole pass. The quantity that actually advances during a pass is
            `settled`: it rewinds to -1 at a restart and climbs to 20, so Math.max(settled + 1, 0)
            counts 1 / 21 -> 21 / 21 as each row settles, clamped to STEPS.length as a guard. It
            is FROZEN while paused because the stepper that advances `settled` is gated by the
            pause control. Done: a single CSS-safe tick + the locked done string. The 21/21 is
            derived from STEPS.length (the live counter); the rest are literal descriptors - AI
            fires at 9 of the 21 steps, one retry was recovered, order #WD-4821. */}
        <div className="wt-foot">
          { done ? (
            <span className="wt-foot-left">
              <span className="wt-foot-tick">✓</span>
              complete — { STEPS.length }/{ STEPS.length } services · AI at 9 decisions · 1 retry · #WD-4821
            </span>
          ) : (
            <>
              <span className="wt-foot-left"><i className="wt-foot-dot" />running</span>
              <span className="wt-foot-right">{ `${Math.min( Math.max( settled + 1, 0 ), STEPS.length )} / ${STEPS.length}` }</span>
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

        /* BROWN TITLE BAR, on instruction. It was #fafafa, which made the chrome the
           lightest thing in a section whose subject is a black panel - the bar drew the
           eye before the content did. A dark brown reads as a warm surround to the black
           body instead of a separate light object sitting on top of it, and it is the one
           warm value on the page so it cannot be confused with the lime accent.
           RIGHT PADDING RESERVES THE PAUSE BUTTON'S FOOTPRINT. .wt-play is absolutely
           positioned, so it is out of flow and would sit on top of .wt-bar-state - 108px is the
           button's own width plus a gap, so the state text ends before the control begins. */
        .wt-bar{height:47px;flex-shrink:0;display:flex;align-items:center;gap:8px;padding:0 108px 0 15px;background:#3b271a;border-bottom:1px solid rgba(209,244,112,.30)}
        .wt-light{width:11px;height:11px;border-radius:50%;flex:0 0 auto}
        /* THREE COLOURS, measured on this bar (#3b271a): amber 6.92:1, purple 2.99:1,
           green 4.42:1. Purple is below 3:1 and that is accepted here deliberately - this whole
           window is aria-hidden decorative chrome and carries no state, so 1.4.11 does not apply,
           and a WCAG ratio measures luminance only while saturated purple against dark brown
           differs strongly in hue; the rendered frame is plainly legible. */
        .wt-light-1{background:#f0a818}
        .wt-light-2{background:#9849e8}
        .wt-light-3{background:#3da35a}
        /* CHROME STATUS LEGIBILITY. These are window chrome, not body prose, so they are raised
           toward a solidly-legible muted white by OPACITY ONLY (no new hex): title .88, state
           .86. Both stay BELOW the solid-#fff step content so the content lines remain the
           loudest glyphs. .88/.86 on #000 clear AA comfortably (~18:1 / ~17:1). */
        .wt-bar-title{margin-left:8px;color:rgba(255,255,255,.88);font-size:14px}
        .wt-bar-state{margin-left:auto;display:flex;align-items:center;gap:7px;color:rgba(255,255,255,.86);font-size:13.5px}
        /* GREEN "live trace" dot. #3da35a is the third light's own value, so no new colour
           enters, and green for a live status is the one hue here that already means
           "healthy/running". Measured on this bar's #3b271a: 4.42:1, well clear of 3:1 on a
           6px decorative dot inside an aria-hidden window. */
        .wt-state-dot{width:6px;height:6px;border-radius:50%;background:#3da35a}

        /* min-height:0 is load-bearing on a flex child that scrolls: without it the
           flex item's automatic minimum size is its content, so it refuses to shrink,
           the panel grows past its 650px and nothing ever scrolls.
           overflow-x:hidden IS LOAD-BEARING: it is what keeps an over-long code line from
           scrolling the whole panel sideways - each step's .wt-code owns its own overflow-x:auto,
           so a long line scrolls inside its block and the page never scrolls horizontally.
           THE SCROLLBAR IS VISIBLE: a .38 thumb on a .08 track, both white alphas on the #000
           panel, so the region reads as scrollable at rest rather than hiding its overflow. */
        .wt-space{position:relative;flex:1;min-height:0;padding:30px 34px 24px;overflow-y:auto;overflow-x:hidden;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.38) rgba(255,255,255,.08)}
        .wt-space::-webkit-scrollbar{width:7px}
        .wt-space::-webkit-scrollbar-track{background:rgba(255,255,255,.08);border-radius:20px}
        .wt-space::-webkit-scrollbar-thumb{background:rgba(255,255,255,.38);border-radius:20px}

        /* THE INTRO. The request line carries the gap the removed illustrative-trace caption
           used to own, so the stream still starts a clear beat below the intro. The caption
           element itself is gone - honesty about the trace being illustrative now lives only in
           the aria .wt-sr text, where it belongs: it is a statement for a reader using assistive
           tech, not a visible label competing with the request line. clamp() scales the request
           fluidly between phone and desktop rather than being stepped down on mobile, per
           .kiro/steering/20-device-compat.md which favours clamp() over fixed sizes. */
        .wt-request{margin-bottom:28px;display:flex;gap:10px;color:#fff;font-size:clamp(16px,1.1vw + 14px,18px);line-height:1.7}
        .wt-caret{color:#d1f470}

        /* Each step fades up as it arrives. The connector is a ::before rule so it
           cannot be knocked out of alignment by content height.
           LIME SEPARATORS: the connector spine between steps carries the accent at low alpha
           instead of neutral white. Low alpha matters - at full strength a 1px lime line down
           the whole panel competes with the lime step dots that mark actual state. */
        .wt-step{position:relative;padding:0 0 26px 36px;opacity:1;transform:translateY(0);animation:wt-in .35s ease both}
        .wt-step::before{content:'';position:absolute;left:5px;top:19px;bottom:-1px;width:1px;background:rgba(209,244,112,.38)}
        .wt-step.is-last::before{display:none}
        @keyframes wt-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

        .wt-dot{position:absolute;left:0;top:4px;width:12px;height:12px;z-index:2;border-radius:50%;border:2px solid rgba(255,255,255,.34);background:#000}

        /* ONE HUE PER SERVICE, and this is a system rather than decoration. Each step IS a named
           service, so a hue that identifies the service is the same use the rotating hero pill
           puts this palette to: one colour per subject.

           STATE IS NOT CARRIED BY HUE: running pulses, done is static, the final step carries a
           tick rollup, and the footer reads "running" / "complete" in words. Three non-colour
           signals, so WCAG 1.4.1 is not engaged: hue says WHICH service, motion and text say
           WHETHER it ran.

           FIVE HUES CYCLE ACROSS THE TWENTY-ONE STEPS, ordered so no two adjacent steps repeat
           (blue, purple, amber, lime, green, blue, amber, purple, green, lime, amber, blue,
           purple, lime, amber, blue, purple, lime, green, amber, green). Step 21 (platform)
           lands on GREEN because that is the one hue whose convention matches "verified /
           healthy". RED IS
           EXCLUDED from the rail deliberately - the error on step 17 (queue) is shown as a red
           "!" line inside the code block, where it means a transient failure that was recovered,
           not an unresolved alarm about the service itself.

           MEASURED ON THE PANEL BODY #000, every value already in this repo:
             lime   #d1f470  16.89:1    amber #f0a818  10.32:1
             green  #3da35a   6.58:1    purple #9849e8  4.45:1
             blue   #2563eb   4.06:1    red    #dc2626  4.35:1 */
        /* THREE PROPERTIES PER STEP, FROM ONE SOURCE OF TRUTH.
           --rgb   the hue as bare channels, so a tint can be mixed with rgba() without a
                   second literal to keep in sync. There is no color-mix() anywhere in this
                   repo, so rgba(var(--rgb),a) is the portable way to get "this hue at 14%".
           --dot   the solid hue, derived from --rgb.
           --ink   the same hue LIFTED until it is legible as text. Defaults to --dot and is
                   overridden only for blue and purple, the two hues below the 4.5:1 text floor. */
        .wt-step{--rgb:209,244,112;--dot:rgb(var(--rgb));--ink:var(--dot)}
        /* --ink EXISTS BECAUSE BLUE AND PURPLE ARE NOT LEGIBLE AS TEXT ON #000 at full chroma.
           The lift is the smallest that clears 4.5:1:
             blue    #2563eb -> #3d74ed   4.51:1
             purple  #9849e8 -> #9f56ea   4.56:1
           amber, lime and green already clear it, so they keep --ink = --dot. */
        .wt-step:nth-child(1){--rgb:37,99,235;--ink:#3d74ed}
        .wt-step:nth-child(2){--rgb:152,73,232;--ink:#9f56ea}
        .wt-step:nth-child(3){--rgb:240,168,24}
        .wt-step:nth-child(4){--rgb:209,244,112}
        .wt-step:nth-child(5){--rgb:61,163,90}
        .wt-step:nth-child(6){--rgb:37,99,235;--ink:#3d74ed}
        .wt-step:nth-child(7){--rgb:240,168,24}
        .wt-step:nth-child(8){--rgb:152,73,232;--ink:#9f56ea}
        .wt-step:nth-child(9){--rgb:61,163,90}
        .wt-step:nth-child(10){--rgb:209,244,112}
        .wt-step:nth-child(11){--rgb:240,168,24}
        .wt-step:nth-child(12){--rgb:37,99,235;--ink:#3d74ed}
        .wt-step:nth-child(13){--rgb:152,73,232;--ink:#9f56ea}
        .wt-step:nth-child(14){--rgb:209,244,112}
        .wt-step:nth-child(15){--rgb:240,168,24}
        .wt-step:nth-child(16){--rgb:37,99,235;--ink:#3d74ed}
        .wt-step:nth-child(17){--rgb:152,73,232;--ink:#9f56ea}
        .wt-step:nth-child(18){--rgb:209,244,112}
        .wt-step:nth-child(19){--rgb:61,163,90}
        .wt-step:nth-child(20){--rgb:240,168,24}
        .wt-step:nth-child(21){--rgb:61,163,90}

        /* Running fills and pulses; done fills. The glow is NEUTRAL white at .10 rather than a
           lime halo: a lime halo around a blue or purple dot reads as two colours fighting. */
        .wt-step.is-running .wt-dot{border-color:var(--dot);background:var(--dot);box-shadow:0 0 0 4px rgba(255,255,255,.10);animation:wt-pulse 1.2s ease-in-out infinite}
        .wt-step.is-done .wt-dot{border-color:var(--dot);background:var(--dot)}
        @keyframes wt-pulse{0%,100%{opacity:.5;transform:scale(.85)}50%{opacity:1;transform:scale(1)}}

        /* THE CODE BLOCK. Each step's lines live in one monospace block that scrolls on its OWN
           x-axis - overflow-x:auto here, .wt-space overflow-x:hidden above - so an over-long
           line never scrolls the whole page. The block is a left-bordered rgba box in the step's
           own hue at low alpha, so it reads as nested under the service dot. */
        .wt-code{margin-top:1px;padding:3px 0 0;overflow-x:auto;display:grid;gap:5px}
        .wt-line{display:flex;align-items:baseline;gap:9px;line-height:1.6;white-space:nowrap}
        /* The call line: a muted "$" prompt, the call text in solid white, the step time
           right-aligned. On desktop the time sits at the end of the row; at <=767px it stacks
           under the call (see the media block). 16px matches the request line's floor. */
        .wt-call{justify-content:space-between;gap:16px}
        .wt-call-main{display:inline-flex;align-items:baseline;gap:9px;min-width:0}
        .wt-prompt{flex:0 0 auto;color:rgba(255,255,255,.70)}
        .wt-call-text{color:#fff;font-size:15.5px}
        /* The cumulative elapsed clock. Muted but readable at .70 (~8:1 on #000), right of the call. */
        .wt-time{flex:0 0 auto;color:rgba(255,255,255,.70);font-size:13.5px}
        /* THE RETURN VALUE. Readable white at .82 (~16:1 on #000) - this is body content, the
           result of the call, so it clears AA comfortably. The "->" glyph takes the step hue. */
        .wt-return .wt-glyph{flex:0 0 auto;color:var(--ink);font-weight:600}
        .wt-return .wt-line-text{color:rgba(255,255,255,.82);font-size:14.5px}
        /* THE NOTE / COMMENT. Muted on purpose - it is the aside, not the event - but still at
           .70 (~8:1 on #000), well clear of AA, so it is legible rather than a bare pass. */
        .wt-note .wt-glyph{flex:0 0 auto;color:rgba(255,255,255,.52)}
        .wt-note .wt-line-text{color:rgba(255,255,255,.70);font-size:14px}
        /* THE SUBSTEP (step 13, ai, compose). Muted-ish white .72 (~8.6:1 on #000), the ">"
           glyph in the step hue so it reads as nested under the call. */
        .wt-sub .wt-glyph{flex:0 0 auto;color:var(--ink);font-weight:600}
        .wt-sub .wt-line-text{color:rgba(255,255,255,.72);font-size:14px}
        /* THE ERROR (step 17, queue, only). Red #dc2626 (4.35:1 on #000) - it is a transient failure
           that the next line recovers, so it reads as a logged error, not an alarm. The error
           TEXT is kept readable by pairing the red glyph with brighter white text. */
        .wt-error .wt-glyph{flex:0 0 auto;color:#dc2626;font-weight:700}
        .wt-error .wt-line-text{color:rgba(255,255,255,.82);font-size:14.5px}
        /* THE INLINE AI DECISION. The "ai >" tag is the one place lime is spent in the panel
           body as a thread marker; the decision TEXT stays white at .82 (~16:1 on #000) so it
           reads as a legible sentence rather than an accent. */
        .wt-ai{align-items:baseline}
        .wt-ai-tag{flex:0 0 auto;color:#d1f470;font-size:13px;font-weight:600;letter-spacing:.04em}
        .wt-ai-text{color:rgba(255,255,255,.82);font-size:14.5px}
        /* THE VERIFICATION ROLLUP (step 21, platform). Lime ticks before each verified service, wrapping
           inline. The item text is readable white at .82; the tick is lime. */
        .wt-rollup{flex-wrap:wrap;white-space:normal;gap:5px 14px}
        .wt-rollup-item{display:inline-flex;align-items:baseline;gap:5px;color:rgba(255,255,255,.82);font-size:14px}
        .wt-rollup-tick{color:#d1f470;font-weight:700}

        /* CONCURRENCY, SHOWN AS COLUMNS. auto-fit rather than a fixed count so the lanes wrap
           cleanly instead of overflowing - they still read as simultaneous, which a horizontal
           scrollbar would destroy. Reasoned at the breakpoints (the panel's inner width is the
           viewport minus the page gutters and the panel's own side padding; browser probes
           cannot run here so this is by arithmetic):
             320px  phone: inner ~= 248px -> floor(248/108) = 2 per row, 3 rows, no overflow.
             375px  phone: inner ~= 303px -> 2 per row, 3 rows, no overflow.
             768px+ panel full width: 5 fit on one row with room to spare.
           auto-fit means no row ever exceeds the track count that fits, so there is never a
           whole-page horizontal scroll; the worst case is 2-per-row on the narrowest phone,
           which still reads as parallel tracks. white-space is reset to normal so the lane
           details can wrap inside their cells rather than forcing the grid wide. */
        .wt-lanes{margin:2px 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(108px,1fr));gap:8px;white-space:normal}
        .wt-lane{padding:9px 10px;background:rgba(255,255,255,.04);border:1px solid rgba(209,244,112,.22);border-radius:6px;display:flex;flex-direction:column;gap:3px}
        /* A short lime rule at the top of each lane, so the five read as parallel tracks
           starting together rather than as five unrelated cards. */
        .wt-lane-bar{display:block;width:22px;height:2px;border-radius:2px;background:#d1f470;margin-bottom:3px}
        /* The lane header: a CSS-drawn status dot beside the channel name. The dot is NOT a
           glyph - several of this site's fonts have no symbol coverage, so a literal circle
           would render as tofu somewhere, the same trap the tick and the window lights avoid. */
        .wt-lane-head{display:flex;align-items:center;gap:7px}
        /* STATUS, CSS-DRAWN. A selected channel takes the green third-light value #3da35a
           (6.58:1 on #000, the same hue the chrome state dot uses for "healthy"); an
           available-but-not-selected channel (voice) takes a hollow, dimmed white ring with no
           fill, so "not selected" reads as off/muted without introducing a new colour. */
        .wt-lane-dot{width:7px;height:7px;flex:0 0 auto;border-radius:50%}
        .wt-lane-dot.is-on{background:#3da35a}
        .wt-lane-dot.is-off{background:transparent;border:1px solid rgba(255,255,255,.30)}
        /* Lane name solid white; lane detail a muted white .74 (~9:1 on #000) BELOW the name so
           the label and its sub-line keep a clear hierarchy rather than both reading as plain
           white. The voice detail now reads "skipped · not eligible". No new hex. */
        .wt-lane-name{color:#fff;font-size:15px;font-weight:600}
        .wt-lane-detail{color:rgba(255,255,255,.74);font-size:14px;line-height:1.45}

        /* THE FOOTER - the ONLY count, and it is live. Running shows the lime dot + "running"
           on the left and the live "N / 21" counter on the right (N = the shown state, frozen while
           paused). Done replaces both with a single CSS-tick + the locked complete string; the
           row height grows to fit it and the text wraps on a narrow panel.
           color raised to .86 by OPACITY ONLY so the footer reads as deliberate chrome rather
           than near-invisible grey - still a muted white BELOW the solid-#fff step content.
           .86 on #000 is ~17:1, well past AA. */
        .wt-foot{flex:0 0 auto;min-height:50px;padding:9px 24px;display:flex;align-items:center;background:#000;border-top:1px solid rgba(209,244,112,.30);color:rgba(255,255,255,.86);font-size:13.5px}
        .wt-foot-left{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
        .wt-foot-tick{color:#d1f470;font-weight:700}
        /* The running dot STAYS LIME, deliberately: it reports live state on the BLACK footer,
           the same claim the lime step dots make inside the panel, so recolouring it would make
           the footer and the steps stop agreeing. Lime on #000 is 11.90:1 here. */
        .wt-foot-dot{width:5px;height:5px;border-radius:50%;background:#d1f470}
        .wt-foot-right{margin-left:auto}

        @media(max-width:767px){
          /* HEIGHT: size to what the visitor can actually see, not to the viewport with the
             chrome hidden. The vh term is the fallback and is declared first; dvh is declared
             second and tracks the visible viewport, so a browser without dvh keeps the vh value.
             The 560px ceiling keeps the panel from dominating a tall phone. */
          .wt-window{height:min(560px,100vh);height:min(560px,100dvh);border-radius:12px}
          .wt-space{padding:23px 18px 60px}
          .wt-bar-state{display:none}
          .wt-step{padding-left:29px}
          /* STACK THE STEP TIME UNDER THE $ LINE. On a phone the call text needs the full
             measure, so the time drops below it rather than squeezing the call. The call row
             switches from a space-between row to a column, and the time aligns to the start
             under the prompt. The code block keeps its own overflow-x:auto, so a long call
             scrolls inside its block and the page never scrolls sideways. */
          .wt-call{flex-direction:column;align-items:flex-start;gap:2px}
          .wt-time{margin-left:16px}
        }

        /* Reduced motion starts on the finished state with the loop paused, so by default this
           only has to stop the decorative loops. It also holds if that reader presses Play: the
           steps still advance, because that is the content, but the entrance slide and the dot
           pulse stay off. */
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
