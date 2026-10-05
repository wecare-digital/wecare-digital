/**
 * Home — the company page.
 *
 * The rotating headline pill is the SAME mechanism as the Grahak OS hero and the
 * VayuLok headline, not a lookalike: identical 2400ms interval, identical easings
 * (.16,1,.3,1 for the wipe and the width glide, .34,1.56,.64,1 for the dot pop),
 * identical white entrance shutter and .33em dot. The three pages are meant to
 * animate as one family, so if you retune one, retune all three.
 *
 * COPY IS PROVISIONAL, and carries the owner's positioning: AI worth having reduces
 * cost and complexity, favours real-world utility over scale, and compounds across
 * domains. The rotation is doing argumentative work rather than decoration - the
 * pill cycling through four unrelated domains is the "across every domain" claim
 * enacted rather than asserted, which is why the headline does not need to say it.
 * The sub-line carries the cost/complexity half. To reword, edit CYCLE_WORDS and
 * .home-sub; nothing else depends on the strings.
 *
 * WORD LENGTH IS A DESIGN CONSTRAINT, not a copy detail, for one measured reason:
 * the pill animates to each word's measured width, so the spread between the
 * shortest and longest word is how far the headline's tail travels on every tick.
 * Measured at 1280px by tools/browser/animcheck.js: consumers 278, enterprises 280,
 * climate tech 290, frontier tech 300, AI applications 361. Spread 83px.
 *
 * See the note above CYCLE_WORDS for why "climate" became "climate tech" - briefly,
 * the bare noun was 178px, which made that spread 183px, and it was also the only
 * entry in the set answering a different question from the other four.
 *
 * The real constraint is NOT the spread, it is reflow: the headline growing to a
 * second line on the longest word only would shift every section below it every
 * 2400ms. That cannot happen here because .home-head-line is display:block, so the
 * pill owns its own line and the h1's line count does not depend on the active word.
 * Verified, not assumed: h1 height is constant for every word at all 21 viewports
 * from 320 to 1920, and constant across a live rotation.
 *
 * Re-measure after changing a word: `node tools/browser/animcheck.js`. The harness
 * is in the repo, under tools/browser/, so that instruction stays true across sandbox
 * resets - it used to name a file that existed nowhere on disk.
 *
 * A unit test cannot see reflow, so src/test/HomePage.test.tsx pins only the one
 * thing it can: no word longer than 18 characters, i.e. long enough to still fit
 * the pill's own line at the narrowest breakpoint.
 *
 * The four tint/dot pairs are reused VERBATIM from the Grahak OS hero - no new
 * colours. Hue maps onto sense the way it does on the other two pages: green for our
 * own domain, blue for communication, purple for intelligence, amber for service.
 * Like the channel tints, this per-subject system sits outside the brand palette by
 * design, which is why lime is absent here.
 *
 * The rotating markup MUST stay inline in this return tree. styled-jsx only attaches
 * its scoping class to elements it can statically see there, so lifting the pill into
 * a variable or a child component silently drops every style and the words render
 * stacked with no pill. That has already happened twice on the other two pages.
 *
 * Classes stay home- prefixed. The globally imported src/styles/*.css declares
 * unscoped rules for generic names and styled-jsx does not shield a page from them.
 */

import React, { useEffect, useRef, useState } from 'react';
import Head from 'next/head';
// next/link, not a bare <a>, for the one internal link on this page. The mega-menu and the
// product CTAs still use <a> - they escape @next/next/no-html-link-for-pages only because
// their hrefs are dynamic expressions the rule cannot resolve, which is a lint accident
// rather than a decision. Link is already the pattern in Layout, PageHeader, Breadcrumbs
// and the dashboard pages, and on a trailingSlash:true export '/contact/' resolves the
// same either way - so this side is the one worth being consistent with.
import Link from 'next/link';
import WorkflowTerminal from '../components/WorkflowTerminal';

/* The SUITE array that used to live here - the three original products plus the seven from
   src/content/products.ts - went with the service-directory grid it fed. See the comment on
   .home-close below for why the home page no longer enumerates services. The products are
   still linked from the header mega-menu on every route and still in the sitemap, so
   src/content/products.ts remains the single source for both. */

// Module scope, not inside the component: the rotation effect reads .length, and a
// literal declared in the body would make that a changing dependency and force an
// exhaustive-deps suppression the way VayuLok needed one.
// Lowercase: these sit mid-sentence, not at the head of one.
//
// THE SET, AND WHY THESE FOUR, AND WHY THE FRAME SAYS "BUILT FOR".
// `consumers` and `enterprises` are audiences; `climate tech` and `frontier tech` are
// fields. Those are two different axes, and the old frame - "Everyday services for" -
// only accepted the first: "Everyday services for climate tech" does not parse, because
// a field is not something you deliver a service to.
// That is the same test that removed `AI applications`, and it applied just as much to
// these two; leaving them in was inconsistent. Rather than cut half the set, the FRAME
// changed. "Everyday AI, built for" is true of all four - you build for consumers and you
// build for climate tech - and it puts AI back above the fold, which had been lost when
// `AI applications` came out.
// Length was deliberate too: 22 characters against the old frame's 21, so the h1's first
// line keeps its visual weight against the pill below it. "Everyday AI for" was rejected
// at 15 characters for leaving that line visibly short.
// DO NOT re-add `AI applications` under this frame: it renders "Everyday AI, built for AI
// applications", with AI twice, and "applications" is what you build rather than a field
// you build for.
// `AI applications` was removed on the owner’s instruction - see the note below. Every entry stays true on the day a single
// offering changes, which is the property the earlier sets did not have.
//
// NO SERVICE NAMES HERE, EVER. travel, rituals, documents, reflection and disputes
// were each in this array at some point and each named a SERVICE. A service can be
// repriced, renamed or discontinued, and on the day one is, the headline is simply
// false. Channel names (WhatsApp, SMS, email, phone) are fine by contrast - they are
// how we reach people, not what we sell, which is why the Grahak OS hero may rotate
// them and this one may not.
//
// Three words were adjusted from the owner's list for grammar, not meaning:
//   consumer   -> consumers    "services for consumer" is not English
//   enterprise -> enterprises  parallel with consumers
//   ai         -> AI           an initialism, and the rest of the page capitalises it
// Revert any of those if the original wording was deliberate.
//
// `AI applications` WAS DROPPED, and it was the outlier that set the pill’s travel.
// Rendered widths at 1280px, from tools/browser/animcheck.js:
//   consumers 278 | enterprises 280 | climate tech 298 | frontier tech 300
//   (`AI applications` measured 361 and is gone; `climate` measured 178 before it
//    became `climate tech`)
// The spread is now about 22px against 83px before, so the pill barely moves per tick.
//
// THE CONSEQUENCE WORTH KNOWING: AI is now mentioned NOWHERE in the hero. The sub-line
// does not name it either, so the only AI claim on this page is "one AI foundation" in
// the flow section below the fold. That is a positioning decision the owner made
// knowingly; if the hero should carry AI again, the sub-line is the place for it, not
// this rotation - the frame is "Everyday services for ___" and every entry has to be
// something you can serve.
// Bare "climate" was much the shortest word in the set, so the pill's tail swung 183px
// every tick against 83px across the other four - 2.2x the movement for one word.
// `climate tech` measures ~290px, which puts the spread back to ~83px. It also fixes
// the sense: "climate" is a domain, while the other four are audiences or kinds of
// thing we build, so the bare noun was the only entry answering a third question.
// It now reads in parallel with `frontier tech` on both counts.
//
// RE-MEASURE AFTER CHANGING A WORD: `node tools/browser/animcheck.js`. That harness
// lives inside the repo precisely so this instruction stays true - it previously named
// a file that existed nowhere on disk, in this comment and three other places.
//
// REFLOW IS THE REAL CONSTRAINT, not the spread. A headline that grows to a second
// line on the longest word only would shift every section below it every 2400ms. That
// cannot happen on this page because .home-head-line is display:block, so the pill
// owns its own line and the h1's line count is independent of which word is showing -
// measured constant for every word at all 21 viewports from 320 to 1920, and again
// through a live rotation. Do not make the pill inline to save a line: the two sibling
// surfaces that do that, /vayulok/ and /grahak-os/, both reflow at narrow widths.
//
// Every tint/dot pair is reused VERBATIM from the Grahak OS hero and the VayuLok
// rotation - no new colours. Five words, five distinct tints, so no two consecutive
// ticks can share a colour without any ordering effort. Lime is deliberately absent:
// this per-subject hue system sits outside the brand palette, which is reserved for
// our own surfaces.
const CYCLE_WORDS = [
  { word: 'consumers', tint: '#fef3c7', dot: '#f0a818' },
  { word: 'enterprises', tint: '#ede9fe', dot: '#9849e8' },
  { word: 'climate tech', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'frontier tech', tint: '#fee2e2', dot: '#dc2626' },
];

const HomePage: React.FC = () => {
  const [ cycleIndex, setCycleIndex ] = useState( 0 );
  const [ cycleW, setCycleW ] = useState<number | null>( null );
  const wordRefs = useRef<( HTMLSpanElement | null )[]>( [] );
  const [ shown, setShown ] = useState( false );

  // The closing band reveals when it scrolls into view. Unlike the hero's one-shot
  // timeout, this cannot fire on a timer: the section sits below the fold, so a timed
  // reveal would play to an empty viewport and be over before anyone scrolled to it.
  //
  // NO REACT STATE FOR THIS ONE, deliberately - see the effect below. The reveal is a
  // visual side-effect with no bearing on what React renders, so it is driven by
  // classList on the node itself.
  const closeRef = useRef<HTMLElement | null>( null );

  // The hero's entrance is armed through this node, for the same reason the closing band is
  // armed through closeRef: the class that hides the start state must be added by JavaScript,
  // never shipped in the markup, or the pill is blank whenever the script does not run.
  const layoutRef = useRef<HTMLDivElement | null>( null );

  useEffect( () => {
    // One-shot entrance, same 60ms beat as VayuLok. No observer: there is a single
    // block above the fold, so there is nothing to reveal on scroll.
    //
    // THE ENTRANCE IS OPT-IN, AND THAT IS THE WHOLE POINT - the same inversion the closing
    // band already uses. The CSS now ships the FINISHED pill: shutter gone, dot popped. This
    // effect adds .is-armed, which is what puts it back to the start state, and it only does
    // so once it knows the animation can actually play. So the failure modes all degrade to
    // "no animation" rather than "no content": without JavaScript, with a failed bundle, or
    // under reduced motion, the pill renders complete.
    //
    // Previously the shutter defaulted to scaleX(1) and the dot to scale(0), with .show
    // removing them - so anything that stopped .show arriving left the headline followed by a
    // blank white lozenge, permanently. Measured with scripting disabled.
    //
    // classList rather than state, deliberately: this is a visual side-effect that changes
    // nothing React renders, which is the case the react-hooks/set-state-in-effect rule
    // exists to steer away from state. The closing band's reveal takes the same approach for
    // the same reason.
    const el = layoutRef.current;
    if ( !el ) return undefined;
    const reduce = typeof window.matchMedia === 'function'
      && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
    // Leave the finished state alone - there is nothing to animate.
    if ( reduce ) return undefined;
    el.classList.add( 'is-armed' );
    const id = window.setTimeout( () => setShown( true ), 60 );
    return () => window.clearTimeout( id );
  }, [] );

  useEffect( () => {
    if ( window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) return;
    const id = window.setInterval(
      () => setCycleIndex( i => ( i + 1 ) % CYCLE_WORDS.length ),
      2400
    );
    return () => window.clearInterval( id );
  }, [] );

  useEffect( () => {
    const el = closeRef.current;
    if ( !el ) return;

    // THE ANIMATION IS OPT-IN, NOT OPT-OUT, and that inversion is the important part.
    //
    // The first version of this rendered the band hidden (opacity:0) and added an "in"
    // class to reveal it. That makes JavaScript load-bearing for reading the page: if the
    // bundle fails, IntersectionObserver is missing, or the effect throws, the closing
    // section is permanently invisible. An entrance effect must never be the reason
    // content cannot be read.
    //
    // So the CSS now ships the FINAL state - everything visible - and this effect adds
    // .is-armed to hide the start state only once it knows it can animate. No JS, no
    // observer, or reduced motion all leave the band fully readable, and the effect is
    // purely additive.
    //
    // It also uses classList rather than setState on purpose. This is a visual
    // side-effect that does not change what React renders, which is exactly the case the
    // react-hooks/set-state-in-effect rule exists to steer away from state; driving the
    // DOM directly is the documented use for an effect, and it avoids a cascading render
    // on every scroll into view.
    if ( typeof IntersectionObserver === 'undefined' ) return;
    if ( window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) return;

    el.classList.add( 'is-armed' );

    const io = new IntersectionObserver(
      entries => {
        if ( entries.some( e => e.isIntersecting ) ) {
          el.classList.add( 'is-in' );
          io.disconnect(); // One-shot: it is an entrance, not a scroll effect.
        }
      },
      // 18% visible before it plays, so the reveal is not already finished by the time
      // the section is properly on screen.
      { threshold: 0.18 }
    );
    io.observe( el );

    return () => io.disconnect();
  }, [] );

  useEffect( () => {
    // Measured, not guessed: the widest word is nearly a third wider than the narrowest,
    // and animating to a measured px value is what makes the pill glide instead of snap.
    //
    // RE-MEASURED ON RESIZE, AND THAT IS NOT BELT-AND-BRACES. This effect used to run only
    // when cycleIndex changed, which left the px width stale on every other input:
    //   - font-size is clamp(36px,4.3vw,60px), so a word's width is a function of viewport
    //     width. During rotation a stale value self-heals at the next 2400ms tick - but
    //     under prefers-reduced-motion the interval never starts, so nothing ever
    //     re-measures. Measured 480 -> 1280: the pill held 182px for a word needing 278px
    //     and overflow:hidden ate 96px, 35% of it, permanently.
    //   - WCAG 1.4.12 requires a page to survive a reader's own letter-spacing and
    //     word-spacing. With those applied the word needs 356.8px against a 278px pill:
    //     22% clipped. That is a Level AA failure, not a cosmetic one.
    //   - a webfont swap changes metrics after first paint too.
    //
    // OBSERVING THE WORD, NOT THE PILL. The pill's width is what this effect sets, so
    // observing it would either never fire or feed itself. The word's content box is the
    // thing that actually changes, so that is what is watched.
    const el = wordRefs.current[ cycleIndex ];
    if ( !el ) return;
    const measure = () => setCycleW( el.offsetWidth );
    measure();
    // Guarded because this also runs in jsdom, where ResizeObserver does not exist.
    if ( typeof ResizeObserver === 'undefined' ) return;
    const ro = new ResizeObserver( measure );
    ro.observe( el );
    return () => ro.disconnect();
  }, [ cycleIndex ] );

  return (
    <>
      {/* NO title AND NO description HERE - BOTH ARE INHERITED FROM _app.tsx ON PURPOSE.
          This Head used to declare `<title>WECARE.DIGITAL</title>` and
          `<meta name="description" content="WECARE.DIGITAL." />`. Because next/head lets a
          page's Head win over _app's, those two lines were silently overriding the sitewide
          metadata on the single most important URL on the site: the home page's title was
          the bare brand name with nothing about what the company does, and its description
          was the brand name followed by a full stop. The sitewide description had already
          been rewritten to "WECARE.DIGITAL builds everyday AI for consumers, enterprises,
          climate tech and frontier tech..." and the home page was the one page never
          receiving it.
          The sitewide values are correct for this route without modification - _app.tsx
          describes the company, and this IS the company page - so the fix is to stop
          overriding them rather than to restate them here. Every other public page declares
          its own because it is about something narrower.
          The canonical stays: it is keyed, so it replaces rather than duplicates _app's,
          and the root is the one canonical that cannot be derived from a pathname. */}
      <Head>
        <link rel="canonical" key="canonical" href="https://wecare.digital/" />
      </Head>
      {/* NO aria-label ON <main>. It carried aria-label="WECARE.DIGITAL home", which was
          character-for-character the same as the header's home link (Header.tsx:299). A
          screen reader therefore announced that string twice - once as a link, once as the
          main landmark - and a landmark whose name repeats a link is no use for navigating,
          which is the only reason to name a landmark at all. A page with a single <main>
          and an <h1> needs no accessible name; the h1 already describes it. */}
      <main className="home-shell">
        <div className={ `home-layout ${shown ? 'show' : ''}`.trim() } ref={ layoutRef }>
          <div className="home-hero">
            {/* THE LIME BRAND BADGE WAS HERE AND IT REPEATED THE HEADER.
                It rendered the same bag mark at 18px plus WECARE.DIGITAL at 14px/600,
                measured 109px below the header's own 60px mark and WECARE./DIGITAL at
                23px/800 - 73px below it on a phone. Two lockups, one under the other,
                saying exactly the same thing, and because the badge sat first in the hero
                it was the first thing anyone read on the site.

                WHY NOT SIMPLY RE-LABEL IT, which was the original plan. The candidate copy
                was "8 services · 1 foundation" - accurate, since STEPS.length is 8 - but
                that exact string is already rendered by WorkflowTerminal on this same page,
                about 380px further down (WorkflowTerminal.tsx:251). Re-labelling would have
                traded a brand duplication for a copy duplication rather than removing one.
                Dropping the mark only (keeping the words) was the other candidate, and it
                halves the problem while leaving the brand name still stated twice inside
                109px.

                So the slot is removed. Colour above the fold is unaffected: the rotating
                pill carries its own tint through amber, violet, green and red. The headline
                now starts 58px higher, and the brand is stated once, by the header, where a
                visitor expects to find it. Putting it back is one line if that reads wrong. */}

            {/* The pill sits on its OWN LINE, and that is a correctness fix rather
                than a layout preference.
                Inline after the frame text, the headline's line count depended on
                which word was showing: measured at 1440px, "reflection" pushed the
                h1 from 75px to 138px while the four shorter words fitted one line,
                so every 2400ms the whole page below jumped by 63px. Widening
                max-width only relocates that to a different viewport - with a word
                whose width varies by 156px inside flowing text, some width will
                always split the line for the long word and not the short one.
                Giving the pill its own block makes line count independent of word
                width, so the glide is free to be as wide as it likes. */}
            <h1 className="home-head">
              <span className="home-head-line">Everyday AI, built for</span>
              <span
                className="home-mark"
                style={ { background: CYCLE_WORDS[ cycleIndex ].tint } }
              >
                <i
                  className="home-mark-dot"
                  style={ { background: CYCLE_WORDS[ cycleIndex ].dot } }
                  aria-hidden="true"
                />
                <span
                  className="home-cycle"
                  style={ cycleW ? { width: `${cycleW}px` } : undefined }
                >
                  {/* The rotation is visual only, so screen readers get the full list
                      once and every animated copy is hidden from them. */}
                  <span className="home-sr-only">{ CYCLE_WORDS.map( c => c.word ).join( ', ' ) }</span>
                  { CYCLE_WORDS.map( ( c, i ) => (
                    <span
                      key={ c.word }
                      ref={ el => { wordRefs.current[ i ] = el; } }
                      className={ `home-cyc-word ${i === cycleIndex ? 'on' : ''}`.trim() }
                      data-wc-translate="true"
                      aria-hidden="true"
                    >{ c.word }</span>
                  ) ) }
                </span>
              </span>
            </h1>

            {/* The one body level the contract allows: 20px/400/1.4/-.125px at
                rgba(0,0,0,.898). Carries the half of the positioning the headline
                cannot - cost and complexity - while the rotation above carries
                breadth. Deliberately one sentence: a second would put two body
                blocks on a page that has no section rhythm yet. */}
            <p className="home-sub">
              Transparent pricing, guided journeys, and dependable support — on one
              shared foundation.
            </p>
          </div>

          {/* The 96px gap on .home-layout is the section rhythm this was reserved for -
              it existed with one child specifically so the next block would land on it.
              WorkflowTerminal styles itself; styled-jsx cannot reach into it from here,
              which is why it takes no className.

              THE TERMINAL NO LONGER SITS ALONE AT FULL WIDTH. On its own it ran the whole
              1252px measure with a 650px black panel and nothing to read beside it, which
              is what made the section feel heavy and left the right-hand side empty. It
              is now the left column of a two-column band, with the section's heading and
              a short list of what the workflow is doing in the right column - so the
              panel is explained rather than just displayed, and the space is used. */}
          <section className="home-flow" aria-labelledby="home-flow-title">
            <div className="home-flow-panel">
              <WorkflowTerminal />
            </div>
            { /* THE COPY FOLLOWS THE PANEL'S NEW SUBJECT. It used to describe an agent -
                 "work that runs itself", plans, low-confidence results - which together
                 with the old stream positioned this as an agentic AI product. It is not:
                 many services run here, they run on one shared foundation, and AI is a
                 feature inside a few of them rather than the thing being sold. */ }
            <div className="home-flow-copy">
              {/* WRITTEN FOR A CUSTOMER, NOT FOR AN ENGINEER. The previous version of this
                  column said "they share one login, one audit trail, one bill and one place
                  to watch them" and called the terminal "the panel". Audit trails, queues,
                  identity and monitoring are how the thing is BUILT; nobody arriving at this
                  page is shopping for those. The old wecare.digital site already had the
                  right instinct and said so outright - customers may never see the
                  underlying systems, but they feel simpler access, clearer communication,
                  prompt follow-ups and more reliable delivery. This column now says that,
                  and the headline gives the black terminal beside it a reason to exist for
                  someone non-technical: it is the part you are not meant to have to look at. */}
              <h2 className="home-flow-title" id="home-flow-title">The part you don’t have to think about.</h2>
              <p className="home-flow-lead">
                Every service runs on the same foundation. Nothing falls between them.
              </p>
              { /* THREE BEATS, EACH ONE SOMETHING A CUSTOMER CAN NOTICE HAPPENING TO THEM.
                   These have now been rewritten twice. First they named components ("Built
                   once, used everywhere"). Then they named consequences but still in our
                   own vocabulary - audit trails, carriers, channels leaving in the same
                   moment, "nobody gets paged". Better, still inward-facing: a carrier
                   outage and an on-call page are OUR problems, and describing how well we
                   handle them quietly asks the reader to care about our operations.
                   Each one is now written from the outside: sign in once, hear from us
                   where you actually look, and get the message late rather than never. The
                   mechanism is still there as the reason to believe it, just no longer the
                   subject of the sentence. */ }
              {/* THE LEAD ABOVE DELIBERATELY DOES NOT LIST THESE THREE. It used to end
                  "...you don’t keep repeating yourself, updates reach you where you are,
                  follow-ups happen automatically, and every experience feels familiar" -
                  which pre-announced all three beats a reader had not reached yet, and
                  duplicated the third one WORD FOR WORD about 150px above it. It also
                  promised four things while only three follow, the fourth being the beat
                  deleted earlier. Do not reintroduce a summary list there.
                  ON "AI FOUNDATION", WHICH HAS NOW GONE BOTH WAYS. It was cut from this
                  lead on the reasoning that the three beats below describe single sign-on,
                  multichannel delivery and automatic retry - none of which is AI - and that
                  labelling plumbing as AI invites a reader to discount the honest parts.
                  The owner then confirmed the positioning, so "AI" was restored here - and
                  has now come out again, because the HERO carries it: the h1 frame reads
                  "Everyday AI, built for". Saying "one AI foundation" one screen below that
                  put AI twice in quick succession, which is the same redundancy this section
                  was cleaned up to remove. The page still says AI once, above the fold, where
                  positioning belongs. The distinction that
                  made it honest while it was here: "one AI foundation" described the
                  PLATFORM the services share, not a claim that each beat below is itself AI. Keep
                  it that way - if a beat ever asserts AI, it needs something behind it.
                  "Nothing falls between them" replaces "You never have to manage the joins
                  between them", which was awkward and put the reader in charge of plumbing
                  they were just told not to think about. */}
              {/* THREE beats. It was four: a fourth read "It remembers the context", which
                  said the same thing as the closing band's "Tell us once. We remember the
                  context." about 200px further down the same page, and the same thing again
                  as the first beat's "your context carries forward". Three claims, one
                  idea. Removing it also evens the two columns of this section, which the
                  sticky copy column had been overrunning.
                  NO CHANNEL NAMES ON THIS PAGE, and that reverses an earlier decision
                  recorded here. They had been restored on the reasoning that the
                  no-service-names rule covers services, not delivery channels - which is
                  still true as a rule. The owner has since scoped it differently: the home
                  page does not promote WhatsApp. "Updates reach you wherever you already
                  are" carries the meaning without naming any channel.
                  Naming SMS, email and phone while omitting WhatsApp was the one option
                  ruled out - in India that reads as an oversight rather than a choice.
                  THIS IS SPECIFIC TO THE HOME PAGE. /grahak-os/ is deliberately
                  WhatsApp-led and its hero still rotates the four channels; do not
                  propagate this edit there. The floating WhatsApp support button stays on
                  every public page including this one - it is a way to reach us, not a
                  claim about what we sell.
                  Beat 1 names no auth mechanism either: no account, no sign-in, no OTP.
                  That was "One account. One continuous experience. / Sign in once..." and
                  promised a login model the owner has not committed to. */}
              <ul className="home-flow-list">
                <li>
                  <strong>Pick up where you left off.</strong>
                  <span>What you’ve already shared stays connected, so the next thing you need isn’t a fresh start.</span>
                </li>
                <li>
                  <strong>Updates find you.</strong>
                  <span>Updates reach you wherever you already are.</span>
                </li>
                <li>
                  <strong>Follow-ups happen automatically.</strong>
                  <span>If something fails or needs chasing, we chase it. You don’t have to.</span>
                </li>
              </ul>
            </div>
          </section>


          {/* THE CLOSING BAND, AND WHY IT IS NOT A SERVICE DIRECTORY ANY MORE.
              This slot held a ten-card grid listing every service by name. The owner's
              objection was that the list is not a fixed set - it is an internal, moving
              inventory - so publishing it on the home page made a promise about scope that
              would be wrong again every time something was added or retired. A closing
              argument does not go stale; a roster does.

              NOTHING IS ORPHANED BY REMOVING IT. Every product page is still linked from
              the header mega-menu, which renders on all sixteen public routes, and all of
              them are still in the sitemap - so the internal linking that made the grid
              worth having is intact without the home page having to enumerate anything.

              THE ANIMATION IS SCROLL-TRIGGERED, NOT LOOPING, and that is the point. There
              are already two continuously moving things above this - the rotating headline
              and the streaming panel - so a third loop would compete with both. This
              reveals once when it comes into view: the lime rule draws itself across and
              the three lines stagger in behind it, which lands the argument and then stops. */}
          <section className="home-close" aria-labelledby="home-close-title" ref={ closeRef }>
            <div className="home-close-panel">
              {/* THIS WAS SELLING A PLATFORM TO A CTO. It said "you do not buy a platform
                  and then wait months to use it", offered "a WhatsApp number that answers, a
                  queue that holds", and promised "nothing to migrate", "no second support
                  queue", "no rebuild". Migration, queues and rebuilds are procurement
                  language: they assume the reader is buying infrastructure and has an
                  engineering team to point at it.
                  That is the wrong audience for this page. The headline above is "Everyday
                  services for travel / rituals / documents", and the old wecare.digital site
                  is explicit about who it serves - everyday Bharat, individuals as much as
                  businesses, with the promise that needs get easier to access, understand and
                  manage. So this now speaks to one person who wants one thing done, and the
                  three lines are that site's own "Tap. Track. Done." written out. */}
              <p className="home-close-eyebrow">Everyday Bharat</p>
              <h2 className="home-close-title" id="home-close-title">
                Start with what you need today.
              </h2>
              {/* THE CONTEXT CLAIM IS DELIBERATELY GONE FROM HERE, and so is the second
                  sentence of the title above. The page was saying "we remember what you
                  already told us" FOUR times: the flow section's first beat, this title,
                  this lead (twice over), and the first point below. Two of those were
                  near-verbatim - "what you’ve already shared" appeared here and in that
                  beat, and "start from scratch" here against "starting over" there. A fifth
                  instance was already deleted in 4d5dcba7. It is now stated twice: once in
                  the flow beat that owns it, once in the point below.
                  The replacement says something the page does not say anywhere else - that
                  you can buy one thing without committing to a bundle - which is what a
                  closing band is for. It also does NOT summarise the three points beneath
                  it, which is the mistake just corrected in the flow section's lead. */}
              <p className="home-close-lead">
                Bring us what’s next. Think it, say it, send it — in your language, your way.
                It starts moving the moment you send it.
              </p>
              <span className="home-close-rule" aria-hidden="true" />
              <ul className="home-close-points">
                {/* "Know the price before you commit" leads, and that order is the point:
                    it is the only concrete, falsifiable promise on the page, and it was
                    sitting last. NOTE it is still a promise with nothing behind it - no
                    price appears anywhere on this page. Do not hardcode one here: the
                    catalog floor is ₹599 today (Viveka) and the owner expects ₹49 once
                    several thousand more products are loaded, so any number typed into this
                    copy starts drifting immediately. Derive it from src/content/wix-catalog.json
                    instead, then it cannot lie. */}
                <li>Know the price before you commit.</li>
                <li>Tell us once. We remember the context.</li>
                <li>See where everything stands.</li>
              </ul>
              {/* A PLAIN <a>, AND IT MUST STAY ONE. This was briefly next/link to silence
                  @next/next/no-html-link-for-pages, and that silently destroyed the button:
                  styled-jsx only attaches its scoping class to lowercase DOM tags, never to
                  a capitalised component, because it cannot know whether the component
                  forwards className to a DOM node. <Link className="home-close-cta"> therefore
                  rendered class="home-close-cta" with no jsx- scope, the compiled
                  .jsx-xxx.home-close-cta rule matched nothing, and the lime pill rendered as
                  bare text under the last bullet. Lint passed the whole time.
                  Do not "fix" this back. The alternatives are worse: an inner <span> carrying
                  the class moves the pill off the focusable element and breaks the focus ring,
                  and :global() would leak this rule out of the component. Every other CTA on
                  the public pages - ProductPage, ContactLocation, the header logo - is a plain
                  <a> for the same reason, and on a static export a full page load is the right
                  behaviour anyway. The cost used to be "one known eslint error, accepted here
                  rather than traded for a broken control" - it is now a recorded exemption at
                  the site, which says the same thing without leaving the lint gate red. */}
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
              <a className="home-close-cta" href="/contact/">Tell us what you need</a>
            </div>
          </section>
        </div>
      </main>
      <style jsx>{`
        /* TWO-COLUMN BAND: terminal left, explanation right.
           The panel is 1fr and the copy column is a fixed 380px rather than the reverse,
           because the terminal's content is monospace at a fixed size and reflows badly
           when squeezed, while prose reflows cleanly at any width.
           align-items:start keeps the copy at the top of the band instead of centring it
           against a 650px panel, which would leave a gap above and below it.
           Collapses to one column at 1024px - below that a 380px sidebar alongside a
           terminal gives both columns too little, and the copy reads better above the
           panel where it introduces it. */
        .home-flow{
          display:grid;
          grid-template-columns:minmax(0,1fr) 380px;
          gap:44px;
          align-items:start;
        }
        .home-flow-panel{min-width:0}
        /* NOT STICKY, AND THE STICKY IT REPLACES WAS DOING NOTHING IT CLAIMED TO.
           This was position:sticky;top:128px under a comment saying the explanation "stays level
           with the panel while the eye follows the stream". It cannot. A sticky element only
           travels inside its own containing block, which here is the 650px grid band, and this
           column measures 570px - so the total sticky travel was 80px, against 1350px of stream
           in the panel beside it. It could stay level with about 6% of the thing it was said to
           follow, and the other 94% it scrolled away exactly like a static element.
           Measured at 1280x800: the column left the sticky position between scrollY 400 and 800
           and was above the viewport from there on.
           So it is static, which is what it was behaving as. align-items:start on the grid is
           what actually keeps it at the top of the band. If the intent ever returns, the honest
           way to get it is a taller band or a shorter column, not a sticky with no room. */
        /* Section h2: 700, HEAVIER than the hero h1's 600. That inversion is deliberate.
           The SIZE is now clamp(28px,3.2vw,40px) with lh 1.08 and ls -1.2px, which is
           identical to .home-close-title below - and that is the point of the change.
           This rule used to read clamp(26px,2.6vw,34px)/1.1/-1px under a comment claiming
           it was "the contract's rung ... the same on every page". It was neither: it
           resolved to 33.28px at 1280 while the other section heading on THIS page
           resolved to 40px, so one page carried two different section-h2 sizes for the
           same job, and the formula appeared nowhere else on the site.
           clamp(28px,3.2vw,40px)/700/1.08/-1.2px is the de-facto site rung - byte for byte
           the same declaration as .home-close-title, .cl-h2, .mo-h2, .brx-h2 and .pdp-h2,
           i.e. 12 headings across 10 public pages. Measure with
           node tools/browser/typecheck.js before changing it. (No backticks in this
           comment on purpose: it sits inside a style jsx template literal, where one
           stray backtick ends the literal and once produced 520 tsc errors.)
           NOTE this is not yet what .kiro/steering/grahak-os-design.md says. The contract
           specifies clamp(32px,4.2vw,54px), which exists on /grahak-os/ and nowhere else;
           reconciling the two is an owner decision, and typecheck.js reports the gap. */
        .home-flow-title{
          font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;
          letter-spacing:-1.2px;color:rgba(0,0,0,.95);margin:0 0 14px;
        }
        /* The one body level: 20px/400/1.4/-.125px. */
        .home-flow-lead{
          font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
          color:rgba(0,0,0,.898);margin:0 0 24px;
        }
        /* EQUAL-HEIGHT ROWS, AND THAT IS THE FIX RATHER THAN A PREFERENCE.
           Each beat's lime rule is a border-inline-start on its own li, so every bar was
           exactly as tall as its own copy - and the bodies wrap to different line counts.
           Measured: 118 / 90 / 90 at 1280, and 118 / 90 / 118 at 390, so the bars were
           unequal AND the pattern changed with the viewport, which is what made it read as
           arbitrary rather than deliberate.
           grid with grid-auto-rows:1fr makes every row the height of the tallest, so the three
           bars match at every width while the rule still spans its whole beat - which is the
           thing the border was for. The alternative was a short fixed marker like
           .wt-lane-bar, but that turns a rule that brackets the text into a bullet beside it.
           The cost is honest: the two shorter beats gain the difference as whitespace, so the
           band grows by that much. Cheaper than copy edited to equal length, which would be
           changing what the page says to fix how it looks. */
        .home-flow-list{margin:0;padding:0;list-style:none;display:grid;grid-auto-rows:1fr;gap:18px}
        /* LIME, AND 3px RATHER THAN 1px - both parts are deliberate.
           This was a 1px #e5e7eb hairline. The owner asked for the separating line to be
           lime green, and lime simply does not survive at 1px: #d1f470 measures about
           1.4:1 against white, so a hairline of it reads as almost nothing on a bright
           screen - the change would have been invisible and the request unmet.
           3px is not a violation of the 1px-static / 2px-hoverable border rule either.
           That rule governs BORDERS ON SURFACES, where thickness signals whether a box can
           be hovered; this is a typographic accent bar beside text, a different role, and
           at 3px it cannot be mistaken for a hover affordance the way 2px could.
           padding-left goes 16px -> 18px to keep the optical gap between bar and text the
           same now that the bar is 2px wider. */
        /* LOGICAL: the accent bar belongs on the edge the reader starts from. As border-left
           it stayed on the physical left in Arabic, where it reads as a bar the text has
           already passed rather than one introducing it. */
        /* THREE COLOURS, ONE PER BEAT - owner's choice of option B from docs/divider-review.
           All three were lime #d1f470 until 2026-09-28.

           WHY THE MOCK'S OWN COLOURS ARE NOT THE ONES HERE. The mock offered amber #f0a818,
           purple #9849e8 and green #3da35a - the first three of the four subject hues - and
           its cost table claimed "all three are >=3:1 on white". That was wrong, and measured
           rather than assumed the moment it came to be built:

             #f0a818 amber    2.04:1   <- fails
             #9849e8 purple   4.72:1
             #3da35a green    3.19:1
             #2563eb blue     5.17:1
             #dc2626 red      4.83:1
             #d1f470 lime     1.24:1   <- what shipped before, and see below

           Amber is out on the measurement. Red is out for a different reason: on a beat that
           reads "Follow-ups happen automatically", a red rule reads as a warning about the
           thing being described. Blue replaces amber, so the set is green / blue / purple -
           3.19, 5.17 and 4.72 - every one above 3:1, and no new colour value anywhere: all
           three are already in this repo's per-subject palette.

           ON THE 3:1 FLOOR NOT STRICTLY APPLYING, because it is worth being honest about
           which rule is doing the work. WCAG 1.4.11 covers graphics REQUIRED to understand
           content, and these rules are decorative - each beat's text is complete without
           them, which is why lime at 1.24:1 was acceptable for as long as it shipped. The
           reason to hold 3:1 now is different: the moment three bars differ, the difference
           is something a reader is meant to perceive, and amber at 2.04:1 beside purple at
           4.72:1 would have read as one washed-out bar and two solid ones - inconsistent
           weight rather than three colours.

           NOT AN ENCODING, so 1.4.1 (Use of Colour) is not engaged: the three beats are told
           apart by their own sentences, and the colours carry no meaning a reader has to
           decode. If a bar colour ever comes to mean something, it needs a second signal.

           WORTH KNOWING: band 1's hero pill rotates these same hues for its four audiences
           (amber consumers, purple enterprises, green climate tech, red frontier tech), so
           purple appears in two places on this page meaning two unrelated things. Judged
           acceptable - the pill shows one hue at a time, rotating, roughly 1000px above three
           static bars - but that is the cost of reusing the palette rather than inventing
           colours, which is the trade the owner picked.

           Hue-to-beat is deliberate, not arbitrary: green for continuity, blue for delivery
           (it is the messaging hue elsewhere in this repo), purple for the automated system. */
        .home-flow-list li{padding-inline-start:18px;border-inline-start:3px solid #3da35a}
        .home-flow-list li:nth-child(2){border-inline-start-color:#2563eb}
        .home-flow-list li:nth-child(3){border-inline-start-color:#9849e8}
        /* Card-heading rung at the small end: 17px/700, a step below .pp-strip-title's
           22px because these sit inside a sidebar rather than on the page. */
        /* BOTH RUNGS WERE OFF THE CONTRACT LADDER, measured against every other text
           element on this page. The title was 17px - the site's BASE body size - where the
           contract's card-heading rung is 22px/700 (the same rung as .pp-strip-title and
           .trust-wordmark). The body was 16px, which made it the SMALLEST text on the page,
           below the 17px base and well below the contract's single body level of 20px/400
           that .home-sub, .home-flow-lead and .home-close-lead all already use. It also
           carried no letter-spacing while every other body rung uses -.125px.
           Both are now on their proper rungs. Everything here is Inter, as it already was -
           there was never a font-family mismatch, only a size one. */
        .home-flow-list strong{display:block;margin:0 0 6px;font-size:22px;font-weight:700;letter-spacing:-.25px;line-height:1.27;color:#000}
        /* Body rung at the neutral colour rgba(0,0,0,.898), matching .home-flow-lead,
           .home-sub and .home-close-lead. It was rgba(0,0,0,.54) (muted grey), which made
           this the only body copy on the page at that colour and read as a different, lighter
           treatment than the closing-band list beside it (which was #1a3a2a green). Both
           lists are now on the one neutral body colour so the two sections read as siblings. */
        .home-flow-list span{display:block;font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.898)}

        /* THE CLOSING BAND. NO margin-top - that was a measured bug, not a style choice.
           .home-layout is a flex column with gap:96px, so every direct child is already
           96px from its neighbour. This rule used to add margin-top:96px on top of that
           gap, and the two are additive: the measured distance from .home-flow to
           .home-close was 192px while hero-to-flow was 96px, so the closing band sat at
           double the page's rhythm. The gap owns the spacing; sections do not. */
        /* (no .home-close rule of its own - see above) */

        /* A tinted panel rather than plain page, because this is the one block on the page
           asking for a decision and it should read as a different surface from the argument
           above it. Same 14px radius and same rgba(209,244,112,.22) tint the rest of the
           site uses for own-surface lime - no new colour. */
        .home-close-panel{
          padding:clamp(28px,4vw,56px);
          border:2px solid #d1f470;border-radius:14px;
          background:rgba(209,244,112,.22);
        }

        .home-close-eyebrow{
          margin:0 0 14px;font-size:12px;font-weight:700;
          letter-spacing:.08em;text-transform:uppercase;color:#1a3a2a;
        }
        /* Section h2 on the contract's 700 rung - heavier than the hero h1's 600, which is
           the inversion the whole site uses. Same clamp as the other section headings so
           they read as siblings. */
        .home-close-title{
          margin:0 0 16px;max-width:19ch;
          font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;
          letter-spacing:-1.2px;color:rgba(0,0,0,.95);
        }
        /* The one body level: 20px/400/1.4/-.125px. max-width in ch, not px, so the measure
           stays ~62 characters whatever the clamp does to the heading beside it. */
        .home-close-lead{
          margin:0;max-width:62ch;
          font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
          color:rgba(0,0,0,.898);
        }

        /* READ THE .is-armed PATTERN BEFORE CHANGING ANY OF THIS.
           Every rule below ships its FINAL, visible state as the default. .is-armed is
           added by JavaScript only when it has confirmed it can animate, and that is what
           hides the start state; .is-in then plays the reveal. The effect is therefore
           additive, and no JS / no IntersectionObserver / reduced motion all leave this
           section fully readable instead of stuck at opacity:0. */

        /* THE RULE DRAWS ITSELF. transform:scaleX is the whole animation - it is
           compositor-only, so it cannot cause layout on any frame, which animating width
           would do 60 times a second. transform-origin:left makes it grow from the left
           edge rather than the centre. */
        .home-close-rule{
          display:block;height:3px;margin:30px 0;background:#d1f470;
          transform-origin:left center;
          transition:transform .62s cubic-bezier(.22,.61,.36,1);
        }
        .home-close.is-armed .home-close-rule{transform:scaleX(0)}
        .home-close.is-armed.is-in .home-close-rule{transform:scaleX(1)}

        /* max-width IS A GUARD, NOT A VISIBLE CHANGE. The three strings are short - the
           longest is 38 characters - so at 1280 each li box ran the full 1126px while its text
           occupied about 300px, and capping it moves nothing today. It is here because the lead
           directly above is capped at 62ch and the title at 19ch, so this list was the one text
           block on the band with no measure at all: the first point that grows past ~75
           characters would have set a line nearly twice the measure of the lead above it.
           Same 62ch as .home-close-lead, because both sit on the same 20px/400 body rung. */
        .home-close-points{margin:0;padding:0;max-width:62ch;list-style:none;display:flex;flex-direction:column;gap:12px}
        /* ON THE SITE'S ONE BODY RUNG: 20px/400/1.4/-.125px, byte for byte the same
           declaration as .home-sub, .home-flow-lead, .home-close-lead and the flow
           section's beat bodies - six elements on this page alone.
           THIS USED TO BE 17px/600 under a comment calling it "the card-heading rung at
           its small end ... claims, not body copy, so they sit above the 16px secondary
           level". Both halves of that were wrong once measured: 17px is the site's BASE
           body size, not a card-heading rung (that rung is 22px/700, which is what the
           flow beats' titles use), and there is no 16px secondary level on this page to
           sit above - 17/600 was simply off the ladder, and after the flow beats moved up
           to 22/700 + 20/400 it became the smallest text in the closing band.
           WHY 400 AND NOT 700. The flow beats earn 22px/700 because a 20px/400 body line
           follows each one and supplies the contrast; these points have no body line, so
           three consecutive bold lines under a 40px/700 h2 would have no internal contrast
           and would rival the heading. Weight is not what marks them as claims - the tick,
           the lime rule above them and the #1a3a2a colour are, which is exactly how the
           flow section separates its own lead (rgba(0,0,0,.898)) from its beat bodies
           (rgba(0,0,0,.54)) while both sit on this same 20/400 rung.
           20px/600 was considered and rejected: it exists nowhere on the site, and
           inventing a rung is the thing the h2 unification was done to stop. */
        .home-close-points li{
          /* padding-inline-start: the 26px is room for the tick, which moves to the other
             edge under rtl along with the ::before below. */
          position:relative;padding-inline-start:26px;
          /* Body rung at the neutral colour rgba(0,0,0,.898), matching .home-close-lead,
             .home-flow-lead, .home-sub and the flow-beat bodies. It was #1a3a2a (brand
             green), which made this list a different treatment from the flow list in
             section 2 (that list was grey .54). Both lists are now unified on the one
             neutral body colour so the two sections read as the same kind of thing. The
             lime tick, the lime rule above and the tinted panel still mark these as
             claims - colour is no longer what does that work. */
          font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.898);
          transition:opacity .5s ease,transform .5s ease;
        }
        /* A tick drawn with two borders on a rotated box: no asset, no request, cannot 404 -
           the same technique as the map pin.
           top follows the line box, it is not a free parameter. At 17px/1.45 the box was
           24.65px tall and top:6px centred the tick on the x-height; at 20px/1.4 the box is
           28px, so the same optical position is 7px. Measured, not scaled by eye. */
        /* THE TICKS CARRY BAND 2'S THREE COLOURS - option 2B from docs/accent-review. All
           three were #1a3a2a until 2026-09-28, and the point is to tie the closing band's
           claims to the beats above them.

           MEASURED ON THE PANEL, NOT ON WHITE. This list sits on .home-close-panel, which is
           rgba(209,244,112,.22) over white and composites to #f5fde0 - a pale yellow-green, so
           a warm mark loses more contrast here than it would on the page:

             #3da35a green    3.04:1
             #2563eb blue     4.92:1
             #9849e8 purple   4.49:1
             #1a3a2a previous 11.89:1
             #f0a818 amber    1.94:1   <- which is why the requested amber is not here

           Amber was in the request and in the mock, and on this panel it renders as a smudge
           beside two solid ticks. Band 2's bars dropped it for the same reason on plain white
           (2.04:1), so the two sections use the same three values and the set stays coherent.

           THE ORDER MATCHES BAND 2 DELIBERATELY: green, blue, purple, top to bottom in both.
           These are three different claims, not the same three claims, so the colours are not
           an encoding - they are a family resemblance. If a colour ever comes to mean a
           specific thing, it needs a second non-colour signal.

           Contrast is lower than the 11.89:1 it replaces, and that is the cost of the change.
           1.4.11 is not engaged - each line reads completely without its tick - but the ticks
           should still be seen, which is why every value clears 3:1 and the weakest is called
           out here rather than discovered later. */
        .home-close-points li:nth-child(2)::before{border-left-color:#2563eb;border-bottom-color:#2563eb}
        .home-close-points li:nth-child(3)::before{border-left-color:#9849e8;border-bottom-color:#9849e8}
        .home-close-points li::before{
          /* inset-inline-start keeps the tick on the reader's starting edge, matching the
             padding above. The two BORDERS stay physical deliberately: rotated -45deg they
             draw a tick, and a tick is a glyph with a settled shape rather than a
             direction - mirroring it would produce a backwards mark that reads as an error
             cross at small sizes. */
          content:'';position:absolute;inset-inline-start:2px;top:7px;
          width:11px;height:6px;
          border-left:2.5px solid #3da35a;border-bottom:2.5px solid #3da35a;
          transform:rotate(-45deg);
        }
        .home-close.is-armed .home-close-points li{opacity:0;transform:translateY(8px)}
        .home-close.is-armed.is-in .home-close-points li{opacity:1;transform:none}
        /* Staggered behind the rule, which finishes at .62s. Three 90ms steps read as one
           settling movement rather than three separate events. */
        .home-close.is-armed.is-in .home-close-points li:nth-child(1){transition-delay:.34s}
        .home-close.is-armed.is-in .home-close-points li:nth-child(2){transition-delay:.43s}
        .home-close.is-armed.is-in .home-close-points li:nth-child(3){transition-delay:.52s}

        /* Full-strength lime with #1a3a2a type: the contract's own-surface pairing.
           THE BORDER IS #1a3a2a, NOT #d1f470, AND THE OLD REASONING HERE WAS THE DEFECT.
           This comment used to read: "Solid lime on the tinted panel still separates because
           the panel is the same hue at 22% - the button is the saturated version of its own
           background, which is why it needs no shadow at rest." Being the same hue is exactly
           what removes the separation. Composited, #d1f470 against this panel's
           rgba(209,244,112,.22) over white measures 1.18:1, and WCAG 1.4.11 wants 3:1 for the
           boundary of a control. The 2px border was the same lime as the fill, so it
           contributed nothing and the button's shape was carried almost entirely by its label -
           on the ONLY action on this page.
           #1a3a2a takes that boundary to 11.85:1. It is not a new colour: it is this button's
           own text colour and the eyebrow's colour in this same panel, so the palette is
           untouched and the fill stays the lime affordance used site-wide.
           It also repairs :hover below, which swaps the fill to #fff and previously left a
           near-invisible lime outline on a pale tint, with translateY and the shadow doing all
           the work of saying "button".
           Re-measure with: node tools/browser/closeprobe.js - it asserts both ratios.
           (No backticks in this comment, deliberately: it sits inside a style jsx template
           literal, where one stray backtick ends the literal. Writing the command in backticks
           here is what broke the build once already - see the same warning above
           .home-flow-title.) */
        .home-close-cta{
          display:inline-flex;align-items:center;min-height:52px;margin-top:32px;
          padding:0 28px;border:2px solid #1a3a2a;border-radius:50px;
          background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;text-decoration:none;
          transition:opacity .5s ease,transform .5s ease,background-color .2s,box-shadow .2s;
        }
        /* THE ARMED STATE HIDES THIS BUTTON FROM SIGHT WITHOUT REMOVING IT FROM THE PAGE, and
           getting that distinction right took two goes.
           It was opacity:0 alone, which left a Tab stop on a control nobody could see: focus
           landed, the ring drew at 1697px down the page, and there was nothing there to look
           at. The fix for that was visibility:hidden, which does remove an element from the tab
           order - and it removed it from the ACCESSIBILITY TREE with it, which turned one defect
           into a worse one. Measured: cta.focus() returned false while armed, and the whole tab
           cycle from page load was five stops - logo, nav trigger, the terminal's Pause, footer
           logo, WhatsApp - and then wrapped to the body. The page's only call to action was in
           none of them. Because Tab could not reach it, Tab could not scroll it into view
           either, so the IntersectionObserver that reveals the band never fired from keyboard
           navigation: a reader using Tab alone could never get to it at all.
           So opacity:0 is back for the hiding, and the original objection is answered directly
           instead - FOCUS REVEALS IT. Sequential focus navigation scrolls the focused element
           into view, so Tab brings the band on screen, the :focus rule below makes the button
           visible in the same moment, and the observer fires too. The ring can no longer draw on
           something invisible, because focusing it is what makes it visible.
           pointer-events:none for the other half: opacity:0 leaves an element clickable, and a
           button nobody can see must not be clickable. Keyboard focus is unaffected by it. */
        .home-close.is-armed .home-close-cta{opacity:0;transform:translateY(8px);pointer-events:none}
        .home-close.is-armed.is-in .home-close-cta{opacity:1;transform:none;pointer-events:auto;transition-delay:.62s}
        /* AFTER .is-in on purpose: same specificity, so source order decides, and focus must
           always win. transition:none because this is an accessibility escape hatch rather than
           an entrance - a reader who has just tabbed to a control should see it now, not fade it
           in over half a second. */
        .home-close.is-armed .home-close-cta:focus{opacity:1;transform:none;pointer-events:auto;transition:none}
        .home-close-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        /* THE FOCUS RING IS OPAQUE. It was rgba(26,58,42,.22), which over this panel's lime
           tint composites to 1.51:1 against the 3:1 WCAG 1.4.11 asks of a focus indicator -
           on the only focusable element inside <main> on the whole page, so a keyboard visitor
           got one Tab stop and almost no sign they had reached it. Dropping the alpha gives
           11.85:1.
           outline-offset:3px STAYS, and it is now load-bearing rather than decorative: the
           border above is the same #1a3a2a, so the 3px band of panel tint between them is what
           keeps the ring legible as a ring instead of reading as a thicker border. */
        .home-close-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

        @media(prefers-reduced-motion:reduce){
          /* Belt and braces. The effect already never arms under reduced motion - the JS
             returns before adding .is-armed - so these rules are the guard for the case
             where the preference changes after arming, when the class is already on the
             node. They kill the movement without hiding anything. */
          .home-close-rule,.home-close-points li,.home-close-cta{transition:none}
          .home-close.is-armed .home-close-rule{transform:scaleX(1)}
          .home-close.is-armed .home-close-points li,
          .home-close.is-armed .home-close-cta{opacity:1;transform:none}
          /* pointer-events too, or a reduced-motion visitor whose preference changed after
             arming would get a CTA that is visible and focusable but not clickable. */
          .home-close.is-armed .home-close-cta{pointer-events:auto}
          .home-close-cta:hover{transform:none}
        }

        @media(max-width:767px){
          /* No margin-top here either. .home-layout's gap drops to 64px at this
             breakpoint, so the narrow-screen rhythm is already handled by the parent - the
             margin that used to be here made it 128px. */
          .home-close-title{max-width:none}
          /* NO font-size OVERRIDE ON THE LEAD HERE. There was one - font-size:18px - and it
             applied to .home-close-lead only, so at 390px this section's lead measured 18px
             while .home-flow-lead directly above it stayed 20px: the same body rung
             rendering at two sizes on one page, which is the defect the h2 unification
             fixed at the heading level. The body rung has no mobile step anywhere else on
             the site (.home-sub and .home-flow-lead both hold 20px down to 320px), so the
             override was the outlier, not the rule. */
        }

        @media(max-width:1024px){
          .home-flow{grid-template-columns:minmax(0,1fr);gap:32px}
          /* Copy first on a narrow screen: it introduces the panel, and a 650px black
             box arriving with no context is the thing that felt overwhelming.
             The position:static that used to be here went with the sticky it was undoing. */
          .home-flow-copy{order:-1}
        }

        /* The font stack is declared here, not inherited. This is the same stack .page
           declares on /grahak-os/, and the declaration is unchanged.
           THE REASON RECORDED HERE WAS WRONG AND IS CORRECTED, not deleted - it claimed a
           dependency that would have made removing an import look dangerous. It said the
           page rendered in Inter "only because @aws-amplify/ui-react's styles.css sets a
           font-family on body", and that Pages.css's --font-sans "contains no Inter at
           all". Measured in a browser: body's computed family is
           'Inter', ui-sans-serif, system-ui, … which is Layout.css:116's value, NOT
           Amplify's ('Inter', -apple-system, BlinkMacSystemFont, …), and Pages.css:60
           begins with 'Inter'. The Amplify stylesheet is no longer a global import;
           src/styles/amplify-base.css holds the handful of rules it was contributing. */
        /* MIN-HEIGHT: the intent is "at least a screenful", and it was written as
           calc(100vh - 69px) with a second value of calc(100vh - 85px) under 768px. Both
           were wrong in the same two ways.
           The subtrahend matched nothing. 69 and 85 correspond to no element in this
           layout - the header is 108px and 96px, the footer 179px and 192px - so they
           could not be maintained against anything, and nothing would have noticed if a
           real height changed.
           100vh is the wrong unit on a phone: it means the viewport with the browser
           chrome HIDDEN, so an element sized to it is taller than what the visitor can
           actually see. dvh is the unit that tracks the visible viewport, declared second
           so a browser without it keeps the vh value rather than nothing.
           This is currently invisible because the page's content is three times a
           viewport, so min-height never binds - which is exactly what makes it a trap for
           whoever shortens this page and then wonders why the fold is in the wrong place. */
        .home-shell{
          min-height:100vh;
          min-height:100dvh;
          padding-top:108px;
          box-sizing:border-box;
          background:#fff;
          font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          color:#1a1a1a;
        }
        /* gap:96px is the SECTION rhythm and stays that even though there is one
           section today - it is what the next block will sit on. The eyebrow-to-
           headline distance is deliberately NOT this gap: it is 20px, owned by
           .home-eyebrow below, matching .hero-eyebrow on Grahak OS and .vl-eyebrow
           on VayuLok. That is why the badge and the headline are wrapped in
           .home-hero rather than being two flex children - as siblings they would
           have been pushed 96px apart. */
        .home-layout{
          width:100%;
          max-width:1300px;
          margin:0 auto;
          padding:80px 24px 96px;
          box-sizing:border-box;
          display:flex;
          flex-direction:column;
          gap:96px;
        }
        /* align-items:flex-start replaces the align-self the eyebrow used to carry.
           Without it the badge is stretched to the full 1300px measure by the flex
           default. It has to be handled on a wrapper rather than passed to the badge:
           styled-jsx does not scope composite components, so anything sent in from
           this page arrives unstyled. */
        .home-hero{
          display:flex;
          flex-direction:column;
          align-items:flex-start;
        }
        /* Hero h1 rung from the design contract: 600, which is LIGHTER than the 700
           section level. That inversion is notion's and is intentional - the same
           note guards .vl-head and .hero-left h1. Do not "correct" it.

           LETTER-SPACING IS IN em, AND IT USED TO BE THREE FIXED PIXEL VALUES.
           font-size here is fluid - clamp(36px,4.3vw,60px) - but the tracking was -2.2px
           with media-query overrides to -1.2px under 768 and -.8px under 480. A fixed px
           value against a fluid font means the OPTICAL tightness changes with the width,
           and measured across the breakpoints it swung from -2.22% to -6.11% of the font
           size: a 2.75x spread. The worst case was 768-820px, where the font is still at
           the 36px clamp floor while the tracking was the value chosen for 60px, so a
           tablet headline carried nearly twice the tightness of the desktop one it was
           tuned for.
           -0.04em is -4% at every size. It deliberately barely moves what was signed off -
           at 1440 the tracking goes from -2.2px to -2.4px and the h1 from 556px to 552px,
           which is not visible - while fixing the tablet case. It also lets both media-query
           overrides go, so there is one number here instead of three and the next change to
           font-size cannot desynchronise them again. */
        .home-head{
          font-size:clamp(36px,4.3vw,60px);
          font-weight:600;
          line-height:1.04;
          letter-spacing:-0.04em;
          color:rgba(0,0,0,.95);
          margin:0;
          max-width:900px;
        }
        /* The single body rung, matching .hero-left p on Grahak OS exactly. The
           contract allows ONE body level across a page and this is it.
           max-width is 560px rather than the headline's 900px: at 20px the 900px
           measure runs to ~110 characters a line, well past the 45-75 the rest of
           the site holds to. 24px above it is the hero's paragraph gap. */
        .home-sub{
          font-size:20px;
          font-weight:400;
          line-height:1.4;
          letter-spacing:-.125px;
          color:rgba(0,0,0,.898);
          margin:24px 0 0;
          max-width:560px;
          /* At a flat 560px this sentence broke after "over" and left "scale." alone
             on the second line. balance evens the two lines instead of filling the
             first greedily. It is a progressive enhancement - unsupported browsers
             get the greedy break, which is the current behaviour, not a regression -
             so it needs no @supports guard. Only safe because this is a short,
             known-length string; balance is capped at a handful of lines and is the
             wrong tool for flowing body copy. */
          text-wrap:balance;
        }

        /* Rotating pill. Same geometry, easing and timings as .hero-mark on Grahak OS
           and .vl-mark on VayuLok - em-based so it tracks the clamp() headline at
           every width. */
        /* Blocks, so the frame and the pill never share a line. See the note in the
           markup: this is what stops the h1's height depending on which word is
           active. margin-top is the optical gap between the two lines - line-height
           1.04 leaves almost no leading, so without it the pill crowds the text. */
        .home-head-line{display:block}
        .home-mark{
          position:relative;display:inline-block;white-space:nowrap;margin-top:.08em;
          padding:.02em .3em .02em .22em;
          border-radius:9999px;
          background:#e0f7c8;
          transition:background-color .52s cubic-bezier(.16,1,.3,1);
        }
        /* White shutter that wipes off to the left on entrance, so the tint appears
           to fill in rather than simply switching on.

           THE DEFAULT IS THE FINISHED STATE - scaleX(0), shutter gone - AND THAT INVERSION
           IS THE FIX. It used to default to scaleX(1): a white panel covering the tint, with
           .home-layout.show removing it once JavaScript had run. So the entrance was OPT-OUT,
           and anything that stopped the class arriving left the pill permanently blank - no
           JS, a failed bundle, a hydration error. Measured with scripting disabled: the
           headline read "Everyday AI, built for" followed by a white lozenge.
           The closing band already does this the right way round and says so at length; this
           is the same pattern. CSS ships what the visitor should end up with, and JavaScript
           adds .is-armed only once it has confirmed it can animate - which is what hides the
           start state. The effect is purely additive, so no JS means no animation rather than
           no content. */
        .home-mark::before{
          content:'';position:absolute;inset:0;
          background:#fff;border-radius:9999px;
          transform:scaleX(0);transform-origin:right center;
          transition:transform .78s cubic-bezier(.16,1,.3,1) .18s;
          z-index:0;
        }
        .home-layout.is-armed .home-mark::before{transform:scaleX(1)}
        .home-layout.is-armed.show .home-mark::before{transform:scaleX(0)}
        /* .33em matches the dot-to-headline ratio measured on notion.com; the tight
           .18em gap keeps it reading as attached to the word. */
        .home-mark-dot{
          position:relative;z-index:1;
          display:inline-block;width:.33em;height:.33em;
          background:#3da35a;border-radius:50%;
          /* margin-inline-end: the dot precedes the word, so the gap has to be on the side
             the word is on. margin-right put the gap behind the dot in Arabic and let the
             dot touch the glyph it is meant to be spaced from. */
          margin-inline-end:.18em;vertical-align:.14em;
          /* scale(1) BY DEFAULT, for the same reason as the shutter above: scale(0) was the
             start state, so without JavaScript the dot never appeared at all. */
          transform:scale(1);
          transition:transform .5s cubic-bezier(.34,1.56,.64,1) .72s;
        }
        .home-layout.is-armed .home-mark-dot{transform:scale(0)}
        .home-layout.is-armed.show .home-mark-dot{transform:scale(1)}
        /* Width is animated from the measured word so the pill glides between
           "Service" and "Intelligence" instead of snapping. overflow:hidden is what
           clips the outgoing word as it slides. */
        /* width:max-content IS THE RESTING WIDTH, and it is what stops the pill shipping
           empty. cycleW starts null, so the first render writes no inline width - and with
           every word absolutely positioned this box had NO intrinsic width at all. It
           computed to 0px and overflow:hidden clipped the word away completely, so the
           headline read "Everyday AI, built for" with nothing after it: for ~200ms on every
           single load (4 painted frames, measured), and permanently with no JavaScript.
           JavaScript still writes an explicit px width over this, which is what animates, so
           the glide is unchanged. */
        .home-cycle{
          position:relative;z-index:1;
          display:inline-block;
          width:max-content;
          height:1.06em;line-height:1.06em;
          vertical-align:baseline;
          overflow:hidden;
          transition:width .52s cubic-bezier(.16,1,.3,1);
          will-change:width;
        }
        .home-cyc-word{
          /* inset-inline-start:0 pins each rotating word to the pill's starting edge. With
             left:0 an Arabic word shorter than the measured pill width floated away from the
             edge the reader begins at, leaving the gap on the wrong side. */
          position:absolute;inset-inline-start:0;top:0;
          white-space:nowrap;
          opacity:0;
          transform:translateY(.42em);
          transition:opacity .42s cubic-bezier(.16,1,.3,1),transform .42s cubic-bezier(.16,1,.3,1);
        }
        /* THE ACTIVE WORD RETURNS TO FLOW, which is what gives .home-cycle a real
           intrinsic width above. The inactive words stay absolute and keep stacking in
           the same place, so nothing about the cross-fade changes.

           display:inline-block IS LOAD-BEARING. position:static alone makes this a
           non-replaced INLINE box, and offsetWidth is 0 for those - so the measuring effect
           would write width:0px over max-content and the pill would collapse on every load
           WITH JavaScript, turning a 200ms flash into a permanent one. Caught by measuring
           a mock, not by reading the diff. */
        .home-cyc-word.on{opacity:1;transform:translateY(0);position:static;display:inline-block}
        .home-sr-only{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }

        @media(max-width:767px){
          .home-shell{padding-top:96px}
          .home-layout{padding:48px 16px 64px;gap:64px}
          /* line-height only. The letter-spacing override that used to sit here is gone:
             tracking is now -0.04em, which scales itself, so restating it per breakpoint is
             what caused the 2.75x optical swing this replaced. */
          .home-head{line-height:1.1}
        }

        /* The rotation itself is already disabled in JS; this settles the pill into
           its resting state so nothing is mid-transition. */
        @media(prefers-reduced-motion:reduce){
          .home-mark::before,.home-mark-dot{transition:none}
          /* Belt and braces, and now SCOPED TO .is-armed so it can actually win.
             These used to read .home-mark::before and .home-mark-dot unscoped, which scored
             (0,1,1) against .home-layout.show .home-mark::before at (0,2,1) - so the correct
             value won only by accident of what the .show rule happened to set, and any edit
             to it would have handed every reduced-motion visitor a blank white pill.
             Both resting states are now the CSS default, so this block no longer has to
             establish them. What it still has to do is beat .home-layout.is-armed, for the
             one case the JS cannot cover: the preference changing AFTER the class is on the
             node. Matching the armed selector's specificity is what makes that work. */
          .home-layout.is-armed .home-mark::before{transform:scaleX(0)}
          .home-layout.is-armed .home-mark-dot{transform:scale(1)}
          .home-cycle{transition:none}
          .home-cyc-word{transition:none}
        }
      `}</style>
    </>
  );
};

export default HomePage;
