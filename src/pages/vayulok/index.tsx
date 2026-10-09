/**
 * VayuLok public product page
 * Bharat Air Intelligence, by WECARE.DIGITAL
 *
 * DELIBERATELY CLEAR. The page is the hero - the tag, the rotating line beneath it and
 * the approved globe beside them - followed by the live VayuLok section. That is the
 * owner's call, and it is still the honest one: no MARKETING copy is invented here.
 * Nothing in this repository describes what VayuLok does beyond the capabilities the
 * rotating words name, so the section below the hero adds no new claims of its own -
 * it shows real fetched air and weather data, or nothing at all when it has none.
 *
 * THE ROTATING WORDS, AND WHICH OF THEM ARE BACKED TODAY.
 *
 * Air, Weather, Forecast and Solar name Google service capabilities that were
 * previously prototyped in the retired Wix/Velo backend. They are not treated as
 * live runtime integrations until corresponding AWS endpoints are implemented:
 *
 *   Air       airquality.googleapis.com/v1/currentConditions:lookup
 *   Weather   weather.googleapis.com/v1/currentConditions:lookup
 *   Forecast  weather.googleapis.com/v1/forecast/days:lookup
 *   Solar     solar.googleapis.com/v1/buildingInsights:findClosest
 *
 * Heatmap and Pollen are ROADMAP, added at the owner's request. Both are real Google
 * APIs, neither is wired here yet:
 *
 *   Pollen    pollen.googleapis.com/v1/forecast:lookup                 (unused)
 *   Heatmap   airquality .../mapTypes/{type}/heatmapTiles/{z}/{x}/{y}  (unused)
 *
 * Heatmap is also the one word in the set that is a VIEW rather than a subject, so it
 * reads oddly in the slot - "Bharat Heatmap Intelligence" parses as intelligence
 * about heatmaps rather than a heatmap of intelligence. Kept because it was asked
 * for; "Pollution" or dropping it are the alternatives if that grates on screen.
 *
 * So the rotation is no longer a pure statement of what is built. When the two
 * endpoints land, delete this caveat.
 *
 * Mechanism is lifted from the Grahak OS hero so the two pages animate identically:
 * measured width so the pill resizes instead of snapping, a pale tint with a
 * saturated dot of the same hue swapping with the word, and the same easing and
 * 2400ms interval. The four tint/dot pairs are reused verbatim from that page - no
 * new colours were introduced for this page, and the hues map cleanly onto the
 * subjects (green air, blue weather, purple forecast, amber solar).
 *
 * ROUTING: _app.tsx keeps an EXACT-MATCH public route allowlist. '/vayulok' is
 * registered there. Without that entry this page would render an empty body with
 * HTTP 200 - a 404 that does not look like one. next.config.js also sets
 * trailingSlash, so the URL is /vayulok/ with the slash.
 *
 * The rotating markup MUST stay inline in the return tree. styled-jsx only attaches
 * its scoping class to elements it can statically see there, so lifting the pill into
 * a variable or a child component silently drops every style and the words render
 * stacked with no pill. This is documented on the Grahak OS hero after it happened.
 *
 * Every class is vl- prefixed, following pp- on the Grahak OS page and ft- in the
 * Footer. The globally imported src/styles/*.css declares unscoped rules for generic
 * names, and styled-jsx does not shield a page from those.
 */

import React, { useEffect, useRef, useState } from 'react';
import PageMeta from '../../components/PageMeta';
import BrandBadge from '../../components/BrandBadge';
import VayuLokApprovedGlobe from '../../components/VayuLokApprovedGlobe';
import VayuLokLive from '../../components/VayuLokLive';


const VayuLokPage: React.FC = () => {
  // Order is hue rhythm as much as grouping. Air + Pollen are what is in the air,
  // Weather + Forecast are conditions, Solar is the adjacent service, Heatmap is the
  // view rather than a subject. Sequencing them this way leaves only one adjacent
  // warm pair (Solar -> Heatmap); the obvious logical order stacked the warm hues
  // consecutively and the pill stopped feeling like it was changing.
  //
  // The first four tint/dot pairs are reused verbatim from the Grahak OS hero. The
  // last two are new, and follow that system's construction rule rather than being
  // picked freely: a pale tint with a saturated dot of the SAME hue, at roughly the
  // 100/600 relationship the existing four use. Reusing one of the four for Heatmap
  // or Pollen was the alternative, but every existing pair is hue-matched to its
  // subject and doubling up would have broken exactly that.
  // Heatmap is a warm TERRACOTTA (#c2591b on #fbe6d4), NOT red: it still reads as
  // heat but honours the owner constraint that #dc2626 - a true red - is forbidden
  // across this page (see .agents/tasks/vayulok-home-aligned-mock/design-tokens.md
  // and owner-constraints.md "NO RED anywhere"). Yellow for Pollen for the obvious
  // reason. Neither touches the brand palette - like the Grahak OS channel tints,
  // these are a per-subject system that sits outside it by design.
  const cycleWords = [
    { word: 'Air', tint: '#e0f7c8', dot: '#3da35a' },
    { word: 'Pollen', tint: '#fef9c3', dot: '#ca8a04' },
    { word: 'Weather', tint: '#dbeafe', dot: '#2563eb' },
    { word: 'Forecast', tint: '#ede9fe', dot: '#9849e8' },
    { word: 'Solar', tint: '#fef3c7', dot: '#f0a818' },
    { word: 'Heatmap', tint: '#fbe6d4', dot: '#c2591b' },
  ];
  const [ cycleIndex, setCycleIndex ] = useState( 0 );
  const [ cycleW, setCycleW ] = useState<number | null>( null );
  const wordRefs = useRef<( HTMLSpanElement | null )[]>( [] );
  const [ shown, setShown ] = useState( false );

  useEffect( () => {
    // The entrance wipe and the dot pop are one-shot, so this does not need an
    // observer the way the Grahak OS page's multiple sections do.
    const id = window.setTimeout( () => setShown( true ), 60 );
    return () => window.clearTimeout( id );
  }, [] );

  useEffect( () => {
    if ( window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) return;
    const id = window.setInterval(
      () => setCycleIndex( i => ( i + 1 ) % cycleWords.length ),
      2400
    );
    return () => window.clearInterval( id );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [] );

  useEffect( () => {
    const el = wordRefs.current[ cycleIndex ];
    if ( el ) setCycleW( el.offsetWidth );
  }, [ cycleIndex ] );

  return (
    <>
      {/* THIS PAGE'S TITLE AND DESCRIPTION WERE THE THINNEST ON THE SITE, measured against
          the other fourteen public routes. The title was "VayuLok by WECARE.DIGITAL" - 25
          characters, where the product pages run 52-68 - and the description was "VayuLok -
          Bharat Air Intelligence, by WECARE.DIGITAL." at 53 characters, which restates the
          brand name twice and tells a reader nothing. Every other page follows one house
          pattern: "<Name> by WECARE.DIGITAL - <what it does>".
          The wording below is assembled from copy already committed elsewhere in the repo
          rather than invented: "Bharat air and weather intelligence" is this route's own
          entry in PUBLIC_PAGE_META in _app.tsx.
          DELIBERATELY NOT LISTING Pollen OR Heatmap even though the hero rotates both -
          docs/grahak-os-handoff.md records that neither has an endpoint wired, and a meta
          description is the wrong place to promise an unbuilt feature. Solar is left out on
          the same caution. Add them here when they are real. */}
      <PageMeta
        title="VayuLok — Bharat air and weather intelligence | WECARE.DIGITAL"
        description="VayuLok by WECARE.DIGITAL — air and weather intelligence for Bharat: air quality, weather and forecasts for wherever you are."
        path="/vayulok/"
      />

      {/* A SECTION, NOT A MAIN, and that is deliberate. VayuLokLive below renders its own
          main.vl-live-shell, and HTML permits exactly one non-hidden main per document -
          two of them is what tools/audit/htmlcheck.js flags at HIGH and what
          src/test/PublicPageTopBand.test.tsx asserts against for the other public pages.
          The component's markup is not ours to change, so the single main landmark is the
          live section and the hero is a labelled region above it. Landmark navigation and
          skip-to-content therefore land on the live widget, which is this page's primary
          interactive content, not on the headline. Purely semantic: every rule in the
          style block below selects .vl-shell by class, so nothing moves on screen. */}
      <section className="vl-shell" aria-label="VayuLok">
        <div className={ `vl-layout ${shown ? 'show' : ''}`.trim() }>
          <div className="vl-hero-grid">
            <div className="vl-hero-copy">
              {/* Same component as the Grahak OS hero and the home page, so the three
                  pills cannot drift apart. The wrapper carries the spacing because
                  styled-jsx cannot style a composite component from here. */}
              <div className="vl-eyebrow">
                <BrandBadge label="VayuLok by WECARE.DIGITAL" />
              </div>

              <h1 className="vl-head">
                <span className="vl-head-line vl-head-line-one">
                  <span>Bharat</span>{ ' ' }
                  <span
                    className="vl-mark"
                    style={ { background: cycleWords[ cycleIndex ].tint } }
                  >
                    <i
                      className="vl-mark-dot"
                      style={ { background: cycleWords[ cycleIndex ].dot } }
                      aria-hidden="true"
                    />
                    <span
                      className="vl-cycle"
                      style={ cycleW ? { width: `${cycleW}px` } : undefined }
                    >
                      <span className="vl-sr-only">{ cycleWords.map( c => c.word ).join( ', ' ) }</span>
                      { cycleWords.map( ( c, i ) => (
                        <span
                          key={ c.word }
                          ref={ el => { wordRefs.current[ i ] = el; } }
                          className={ `vl-cyc-word ${i === cycleIndex ? 'on' : ''}`.trim() }
                          data-wc-translate="true"
                          aria-hidden="true"
                        >{ c.word }</span>
                      ) ) }
                    </span>
                  </span>
                </span>
                <span className="vl-head-line vl-head-line-two">
                  <span className="vl-head-tail">Intelligence</span>
                </span>
              </h1>
            </div>

            <div className="vl-hero-visual">
              <VayuLokApprovedGlobe />
            </div>
          </div>
        </div>
      </section>

      {/* LIVE CONTENT, DIRECTLY BELOW THE HERO - which is what the .vl-shell note beside
          the padding rule has described ever since the forced 100vh came off, and what
          this file's own header describes. The markup went missing in a revert of the
          "Filling the Gap" globe, leaving both comments pointing at a section that was no
          longer rendered. Restored here as a SIBLING of the hero, not a child: the
          component's own root wraps a main.vl-live-shell, and nesting that inside another
          main would be invalid - which is also why the hero above is a section.
          src/test/VayuLokLivePageWiring.test.tsx guards this placement; the section has
          already been lost twice to edits of the surrounding markup.
          A PLAIN STATIC IMPORT, deliberately not next/dynamic. VayuLokLive touches
          window, document and google only inside effects and in helpers that return
          early on typeof window === 'undefined', and it imports deck.gl dynamically
          inside the layer-activation effect, so it prerenders safely under the
          output:'export' build. ssr:false would merely empty this section out of the
          exported HTML for no SSR gain. It is self-styling under a vl-live- scope, so
          it needs no wrapper and no rule here.
          WHAT THE KEYLESS PATH ACTUALLY RENDERS - stated precisely, because the first
          version of this comment overstated it. With NEXT_PUBLIC_GOOGLE_MAPS_KEY unset,
          which is every CI and sandbox run, the component injects no Maps JS, mounts no
          interactive canvas, shows no live air or weather panels and issues no fetch
          calls - but it DOES render a Google Maps embed iframe where the canvas would
          be, eagerly, pinned to the default place. That iframe is a third-party request
          on load, so this path is degraded, not network-silent. The component's own test
          pins it under the name "shows the keyless map", so do not describe this page as
          map-free while the key is absent. */}
      <VayuLokLive />


      <style jsx>{`
        /* Header is fixed at 108px, 96px under 767px - the same offsets the home
           page uses, so the two public shells start at the same place.
           The font stack is declared rather than inherited, matching .page on
           /grahak-os/ and .home-shell. The declaration stays; the reason beside it was
           wrong and is corrected. It said the typeface came "only via the body rule in
           @aws-amplify/ui-react's styles.css" and that Pages.css's --font-sans "has no
           Inter in it". Measured: body's computed family is Layout.css:116's
           'Inter', ui-sans-serif, system-ui, … and Pages.css:60 starts with 'Inter'.
           The Amplify stylesheet is not a global import any more - see
           src/styles/amplify-base.css. */
        /* No min-height: the hero used to fill the viewport when it was the whole
           page, but the live VayuLok section now renders directly below it, so a
           forced 100vh left a ~240px empty band between the hero content and the
           live content. The hero is now only as tall as its content; padding-top
           still clears the fixed header. */
        .vl-shell{padding-top:108px;box-sizing:border-box;background:#fff;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1a1a1a}
        /* No flex gap: the only gap in the page is under the badge and .vl-eyebrow
           owns it. A column gap would apply to nothing and quietly mislead whoever
           adds the second element. */
        .vl-layout{width:100%;max-width:1300px;margin:0 auto;padding:80px 24px 48px;box-sizing:border-box}
        .vl-hero-grid{display:grid;grid-template-columns:minmax(0,.88fr) minmax(540px,1.12fr);gap:48px;align-items:center}
        .vl-hero-copy{min-width:0}
        .vl-hero-visual{min-width:0;width:100%}

        /* Spacing only. The badge paints itself inside BrandBadge. */
        .vl-eyebrow{margin:0 0 20px}

        /* Hero h1 level from the design contract: 600 weight, not the heavier 700
           the section level uses. That inversion - section headings heavier than the
           h1 - is notion's and is intentional, so do not "correct" it here. */
        .vl-head{font-size:clamp(36px,4.3vw,60px);font-weight:600;line-height:1.04;/* TRACKING IN em, NOT px. A fixed px value against a fluid clamp() font means the
             OPTICAL tightness changes with the viewport: measured across the breakpoints it ran
             -2.22% to -6.11% of the font size, a 2.75x spread, worst at 768-820px where the font
             is still on its 36px floor while the tracking was chosen for 60px. -0.04em is -4% at
             every size, and it lets both media-query overrides go - restating it per breakpoint
             is what caused the spread. index.tsx fixed this; these three copies had not. */
          letter-spacing:-0.04em;color:rgba(0,0,0,.95);margin:0;max-width:900px}
        .vl-head-line{display:block}
        .vl-head-line-one{display:flex;align-items:baseline;gap:.14em;white-space:nowrap;width:max-content;max-width:100%}
        .vl-head-line-two{display:block;margin-top:.08em}
        .vl-head-tail{display:inline-block;white-space:nowrap}

        /* Rotating pill. Same geometry, easing and timings as .hero-mark on the
           Grahak OS page - em-based so it tracks the clamp() headline at every width. */
        .vl-mark{
          position:relative;display:inline-block;white-space:nowrap;
          padding:.02em .3em .02em .22em;
          border-radius:9999px;
          background:#e0f7c8;
          transition:background-color .52s cubic-bezier(.16,1,.3,1);
        }
        /* White shutter that wipes off to the left on entrance, so the tint appears
           to fill in rather than simply switching on. */
        .vl-mark::before{
          content:'';position:absolute;inset:0;
          background:#fff;border-radius:9999px;
          transform:scaleX(1);transform-origin:right center;
          transition:transform .78s cubic-bezier(.16,1,.3,1) .18s;
          z-index:0;
        }
        .vl-layout.show .vl-mark::before{transform:scaleX(0)}
        /* .33em matches the dot-to-headline ratio measured on notion.com; the tight
           .18em gap keeps it reading as attached to the word. */
        .vl-mark-dot{
          position:relative;z-index:1;
          display:inline-block;width:.33em;height:.33em;
          background:#3da35a;border-radius:50%;
          margin-right:.18em;vertical-align:.14em;
          transform:scale(0);
          transition:transform .5s cubic-bezier(.34,1.56,.64,1) .72s;
        }
        .vl-layout.show .vl-mark-dot{transform:scale(1)}
        /* Width is animated from the measured word so the pill glides between "Air"
           and "Forecast" instead of snapping. overflow:hidden is what clips the
           outgoing word as it slides. */
        /* PORTED FROM THE HOME BAND. Four implementations of this hero exist and every one
           carried the same defects; see docs/home-design-audit-20260926.md.

           width:max-content is the RESTING width. cycleW starts null, so the first render
           writes no inline width - and with every word absolutely positioned this box had no
           intrinsic width at all. It computed to 0px and overflow:hidden clipped the word
           away: ~200ms on every load, permanently with no JavaScript. JS still writes an
           explicit px width over this, which is what animates, so the glide is unchanged. */
        .vl-cycle{
          width:max-content;
          position:relative;z-index:1;
          display:inline-block;
          height:1.06em;line-height:1.06em;
          vertical-align:baseline;
          overflow:hidden;
          transition:width .52s cubic-bezier(.16,1,.3,1);
          will-change:width;
        }
        .vl-cyc-word{
          position:absolute;left:0;top:0;
          white-space:nowrap;
          opacity:0;
          transform:translateY(.42em);
          transition:opacity .42s cubic-bezier(.16,1,.3,1),transform .42s cubic-bezier(.16,1,.3,1);
        }
        /* The ACTIVE word returns to flow, which is what gives the box above a real
           intrinsic width. The inactive words stay absolute and keep stacking.

           display:inline-block IS LOAD-BEARING: position:static alone makes this a
           non-replaced inline box whose offsetWidth is 0, so the measuring effect would
           write width:0px over max-content and the pill would collapse on every load WITH
           JavaScript - a 200ms flash turned permanent. */
        .vl-cyc-word.on{opacity:1;transform:translateY(0);position:static;display:inline-block}
        .vl-sr-only{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }

        @media(max-width:1024px){
          .vl-hero-grid{grid-template-columns:minmax(0,.9fr) minmax(460px,1.1fr);gap:32px}
        }
        @media(max-width:860px){
          .vl-hero-grid{grid-template-columns:1fr;gap:36px}
          .vl-hero-visual{max-width:760px;margin:0 auto}
        }
        @media(max-width:767px){
          .vl-shell{padding-top:96px}
          .vl-layout{padding:48px 16px 32px}
          .vl-head{line-height:1.1}
          .vl-hero-grid{gap:28px}
        }
        @media(max-width:359px){
          .vl-head{font-size:clamp(31px,9vw,36px)}
          .vl-head-line-one{gap:.1em;transform-origin:left center}
          .vl-mark{padding-inline:.18em .24em}
        }

        /* The rotation itself is already disabled in JS; this settles the pill into
           its resting state so nothing is mid-transition. */
        @media(prefers-reduced-motion:reduce){
          .vl-mark::before,.vl-mark-dot{transition:none}
          /* scaleX(0) is the RESTING state. scaleX(1) is the START state - a white
             shutter covering the tint - which is what this used to set. It never bit only
             because .vl-layout.show out-specifies it (0,2,1 vs 0,1,1). */
          .vl-mark::before{transform:scaleX(0)}
          .vl-mark-dot{transform:scale(1)}
          .vl-cycle{transition:none}
          .vl-cyc-word{transition:none}
        }
      `}</style>
    </>
  );
};

export default VayuLokPage;
