/**
 * VayuLok public product page
 * Bharat Air + Weather Insights, by WECARE.DIGITAL
 *
 * DELIBERATELY CLEAR. The page is the hero - the tag, the rotating line beneath it and
 * the approved globe beside them - followed by the live VayuLok section. That is the
 * owner's call, and it is still the honest one: no MARKETING copy is invented here.
 * Nothing in this repository describes what VayuLok does beyond the capabilities the
 * rotating words name, so the section below the hero adds no new claims of its own -
 * it shows real fetched air and weather data, or nothing at all when it has none.
 *
 * The hero names the live capabilities surfaced by this page: Air, Weather, Forecast,
 * Conditions, History and Heatmap. The page keeps the lighter hero presentation while Weather
 * remains a first-class live section below.
 *
 * The hero is the shared RotatingHero, as on Grahak OS, so the two pages animate identically:
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
 * The globe markup passed as RotatingHero's `visual` MUST stay inline in this return
 * tree. styled-jsx only attaches its scoping class to elements it can statically see
 * there, which is what lets .vl-hero-visual below style it; lifting it into a variable
 * or a child component silently drops those rules.
 *
 * Every class is vl- prefixed, following pp- on the Grahak OS page and ft- in the
 * Footer. The globally imported src/styles/*.css declares unscoped rules for generic
 * names, and styled-jsx does not shield a page from those.
 */

import React from 'react';
import PageMeta from '../../components/PageMeta';
import Breadcrumbs from '../../components/Breadcrumbs';
import RotatingHero from '../../components/RotatingHero';
import VayuLokApprovedGlobe from '../../components/VayuLokApprovedGlobe';
import VayuLokLive from '../../components/VayuLokLive';

/*
 * SOCIAL CARD. This page uses the sitewide square brand card from _app.tsx
 * (o/stream/media/m/wecare-digital.png, 1080x1080, twitter:card 'summary'). A VayuLok-specific
 * 1200x630 card at o/stream/media/m/vayulok-social.png was wired here but never uploaded, so
 * every share of /vayulok/ advertised an og:image that redirected to the home page (checked
 * 2026-10-25). Pass PageMeta an `image` again once that object exists in the bucket.
 */

/*
 * STRUCTURED DATA. Only a WebApplication node that accurately describes the live VayuLok app.
 * There is deliberately NO FAQPage here: the visible "About VayuLok" FAQ was removed from the
 * page, and FAQ structured data must only mark up content that is actually present (the sitewide
 * FAQ schema was removed earlier for exactly that reason).
 */
function vayulokJsonLd(): Record<string, unknown>[] {
  return [
    {
      '@context': 'https://schema.org',
      '@type': 'WebApplication',
      '@id': 'https://wecare.digital/vayulok/#webapp',
      name: 'VayuLok',
      alternateName: 'VayuLok by WECARE.DIGITAL',
      url: 'https://wecare.digital/vayulok/',
      applicationCategory: 'HealthApplication',
      operatingSystem: 'Web Browser',
      description: 'Air and weather insights for Bharat: live air quality, weather, a 96-hour forecast and recent history for a chosen location.',
      inLanguage: 'en-IN',
      isAccessibleForFree: true,
      provider: { '@id': 'https://wecare.digital/#organization' },
      offers: { '@type': 'Offer', price: '0', priceCurrency: 'INR' },
    },
  ];
}


const VayuLokPage: React.FC = () => {
  const [ mode, setMode ] = React.useState<'air' | 'weather'>( 'air' );
  const [ globeLocation, setGlobeLocation ] = React.useState<{
    name: string;
    addr?: string;
    lat: number;
    lng: number;
    regionCode?: string;
  } | null>( null );
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
  // Every rotating word names a capability VayuLok actually ships today. 'Pollen' and 'Solar'
  // were removed: neither has a wired endpoint (Google Pollen has no India coverage; Solar is
  // unbuilt), so advertising them in the hero overstated the product. They are replaced by two
  // real, prominent features. "Conditions" replaces the unsupported Pollen promise while
  // accurately covering the live Air current-condition experience.
  const capabilityWords = {
    air: { word: 'Air', tint: '#e0f7c8', dot: '#3da35a' },
    weather: { word: 'Weather', tint: '#dbeafe', dot: '#2563eb' },
    forecast: { word: 'Forecast', tint: '#ede9fe', dot: '#9849e8' },
    conditions: { word: 'Conditions', tint: '#e0f7c8', dot: '#3da35a' },
    history: { word: 'History', tint: '#fef9c3', dot: '#ca8a04' },
    heatmap: { word: 'Heatmap', tint: '#fbe6d4', dot: '#c2591b' },
  };
  const cycleWords = mode === 'weather'
    ? [ capabilityWords.weather, capabilityWords.forecast, capabilityWords.conditions, capabilityWords.history, capabilityWords.heatmap, capabilityWords.air ]
    : [ capabilityWords.air, capabilityWords.conditions, capabilityWords.history, capabilityWords.heatmap, capabilityWords.weather, capabilityWords.forecast ];

  const countryForGlobeCity = ( id: string ): string | undefined => ( {
    delhi: 'IN', bengaluru: 'IN', dubai: 'AE', moscow: 'RU', london: 'GB',
    beijing: 'CN', tokyo: 'JP', singapore: 'SG', sydney: 'AU', washington: 'US', saopaulo: 'BR',
  } as Record<string, string> )[ id ];
  return (
    <>
      {/* THIS PAGE'S TITLE AND DESCRIPTION WERE THE THINNEST ON THE SITE, measured against
          the other fourteen public routes. The title was "VayuLok by WECARE.DIGITAL" - 25
          characters, where the product pages run 52-68 - and the description was "VayuLok -
          Bharat Air Insights, by WECARE.DIGITAL." at 53 characters, which restates the
          brand name twice and tells a reader nothing. Every other page follows one house
          pattern: "<Name> by WECARE.DIGITAL - <what it does>".
          The wording below is assembled from copy already committed elsewhere in the repo
          rather than invented: "Bharat air and weather insights" is this route's own
          entry in PUBLIC_PAGE_META in _app.tsx.
          DELIBERATELY NOT LISTING Pollen OR Heatmap even though the hero rotates both -
          docs/grahak-os-handoff.md records that neither has an endpoint wired, and a meta
          description is the wrong place to promise an unbuilt feature. Solar is left out on
          the same caution. Add them here when they are real. */}
      <PageMeta
        title="VayuLok — Bharat air and weather insights | WECARE.DIGITAL"
        description="VayuLok by WECARE.DIGITAL — live air quality, weather, forecasts, history and heatmaps for a chosen location."
        path="/vayulok/"
        jsonLd={ vayulokJsonLd() }
      />

      <main className="vl-page">
        <RotatingHero
          insideMain
          mobileFoundation
          ariaLabel="VayuLok"
          badgeLabel="VayuLok by WECARE.DIGITAL"
          frame="Nano Climates"
          words={ cycleWords }
          pillKey={ mode }
          sub={ <>Ultra-precise air and weather intelligence<br />to understand conditions, change,<br />and emerging patterns.</> }
          visual={ (
          <div className="vl-hero-visual">
            <VayuLokApprovedGlobe
              mode={ mode }
              onModeChange={ setMode }
              onSelectLocation={ city => {
                setGlobeLocation( {
                  name: city.name,
                  addr: city.name,
                  lat: city.lat,
                  lng: city.lng,
                  regionCode: countryForGlobeCity( city.id ),
                } );
              } }
            />
          </div>
          ) }
        >
          {/* THE VISIBLE BREADCRUMB mirroring _app.tsx's BreadcrumbList for /vayulok/:
              Home -> 'VayuLok' (the exact PUBLIC_PAGE_META name). Rendered as the hero's
              child, directly under the hero copy (RotatingHero owns the single h1). No
              page-level BreadcrumbList is emitted here: _app.tsx owns the single one for this
              PUBLIC_PAGE_META route, and this page's own WebApplication JSON-LD is unchanged. */}
          <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'VayuLok' } ] } />
        </RotatingHero>

        {/* The live air/weather application stays directly below the shared product hero.
            VayuLokLive no longer owns a second <main>; this page owns the one primary
            landmark so the same Header -> unified hero -> content -> Footer structure
            applies here as it does to every other public product page. */}
        <VayuLokLive mode={ mode } onModeChange={ setMode } externalLocation={ globeLocation } />
      </main>


      <style jsx>{`
        /* The hero's shell, headline, badge spacing and subtext are RotatingHero's own rh-*
           rules. This page keeps only what is its own: the globe column and the split. */
        /* The two columns read as a deliberate, balanced pair: the copy holds a
           little under half the width and the globe a little over, with the globe
           CENTRED in its column and capped so it never dwarfs the headline. The
           globe's own left-side info panel lives inside the right column, which is
           why the gap is generous: it keeps the panel clear of the headline.
           These rules used to style .vl-hero-grid and now retune RotatingHero's
           .rh-split, so the globe keeps its own proportions and stays beside the copy
           down to 861px, where the shared split would stack at 1024px. .vl-page makes
           the selector outrank the component's own .rh-split at every width. */
        .vl-page :global(.rh-layout){gap:48px;padding-bottom:32px}
        .vl-page :global(.rh-split){display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:24px;align-items:center}
        .vl-page :global(.rh-hero){align-self:start;padding-top:8px}
        .vl-page :global(.rh-sub){max-width:470px}
        .vl-hero-visual{min-width:0;width:100%;display:flex;justify-content:flex-start;align-items:center;transform:translate(-28px,20px)}
        .vl-hero-visual :global(.vag-shell){width:min(116%,840px);max-width:840px}

        @media(max-width:1100px){
          .vl-page :global(.rh-split){grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);gap:24px}
          .vl-hero-visual{transform:translate(-14px,16px)}
          .vl-hero-visual :global(.vag-shell){width:min(112%,760px);max-width:760px}
        }
        @media(max-width:860px){
          .vl-page :global(.rh-split){grid-template-columns:1fr;gap:28px}
          .vl-hero-visual{max-width:800px;margin:0 auto;justify-content:center;transform:translateY(12px)}
          .vl-hero-visual :global(.vag-shell){width:100%;max-width:800px}
        }
        @media(max-width:767px){
          .vl-page :global(.rh-split){gap:24px}
          .vl-page :global(.rh-sub){max-width:34ch}
          .vl-hero-visual{width:100%;max-width:100%;overflow:hidden;transform:none}
          .vl-hero-visual :global(.vag-shell){width:100%;max-width:560px}
          /* VayuLok's longest live capability word is "Conditions" and the frame sits on its
             own line, so it does not need Grahak/contact's narrow 32/28px safety rungs.
             Keep the canonical 40px app hero through the phone/foldable range; devicecheck
             owns the proof and should force a measured exception if this ever stops fitting. */
          .vl-page :global(.rh-shell.uses-mobile-foundation .rh-head){font-size:var(--public-mobile-hero-size)}
        }
      `}</style>
    </>
  );
};

export default VayuLokPage;
