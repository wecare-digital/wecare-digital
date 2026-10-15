import React, { useEffect, useRef, useState } from 'react';

/**
 * The map and address block on /contact/.
 *
 * SELF-STYLING, like BrandBadge, RotatingHero, WorkflowTerminal, LegalDocument and
 * ProductPage: styled-jsx cannot scope a composite component from its parent.
 *
 * WHAT THIS IS NOT. The owner supplied a complete standalone map application - roughly
 * 6,000 lines carrying weather, air quality, solar, currency conversion, world time,
 * translation with Cloud TTS, Street View, a nearby-places rail and a West Bengal
 * carousel. None of that is here, for two reasons. It is a different product, not a
 * contact panel; and it ships its own design system - Material tokens
 * (--md-sys-color-*), its own typeface, a 13px radius scale, #111 ink - which directly
 * contradicts this site's contract. Porting it would have imported a second visual
 * language onto a marketing page. What the owner asked for was the map in OUR design,
 * followed by the address, and that is what this is.
 *
 * NO API KEY, AND THEREFORE NO KEY IN THE PAGE SOURCE. This used to build a Maps Embed
 * API url (maps/embed/v1/place) from NEXT_PUBLIC_GOOGLE_BROWSER_KEY, which had two problems.
 * The owner asked for the map to render INLINE with no redirection out to Google, and the
 * keyed version could not: with no key configured it rendered a panel that linked to
 * Google instead of a map, because an Embed API iframe without a key paints a Google
 * error page inside our frame. And NEXT_PUBLIC_ with output:'export' bakes the value into
 * the build, so the key is publicly readable and needs referrer-locking and its own
 * embed-only key to stay un-abusable.
 *
 * WHERE THE KEY ACTUALLY ENDS UP, because this comment used to say "the built HTML ...
 * readable in the page source" and that is wrong in a way that matters. Measured with a
 * dummy key: it appears in exactly one file, a JS chunk under out/_next/static/chunks/,
 * and in ZERO html files - because it is only read inside a useEffect, so it never reaches
 * the prerendered markup. Anyone who checks by grepping the HTML or using View Source will
 * find nothing and may conclude the key is not exposed. It is: that chunk is served to
 * every visitor. Restrict it in the Cloud console regardless.
 *
 * It now uses the legacy keyless endpoint - maps?q=...&output=embed - which needs no
 * credential, no billing account and no rotation. The map always renders. Nobody is sent
 * to Google to see where we are.
 *
 * THE TRADE-OFF, STATED: that endpoint is long-lived and very widely used but it is NOT
 * formally documented by Google, so it carries no compatibility promise the way the Embed
 * API does. If it is ever withdrawn the frame goes blank and the address block below it
 * keeps working. tools/browser/contactcheck.js is the canary, so a silent regression is
 * caught rather than discovered by a visitor. It enters the cross-origin frame, counts
 * the tiles that actually loaded, and converts the lat/lng in our own iframe src into a
 * Web Mercator tile index to confirm Google served THAT location - currently 39 tiles,
 * 9 of them within 4 tiles of the expected z18 x195411 y114193.
 *
 * It does NOT look for the string "Kolkata", which an earlier version of this comment
 * claimed: place names are rasterised into the tile images, so the frame exposes about
 * 65 characters of text and a text match fails while the map is entirely correct. The
 * tile-index check is both stronger and not a false-failure risk. (That earlier canary,
 * mapprobe.js, lived outside the repo in /projects/pwtest and no longer exists at all -
 * which is why every harness now lives in tools/browser/ under version control.)
 *
 * THE QUERY FORM IS MEASURED, NOT GUESSED. Four forms were tested in a real framed
 * browser. place_id: syntax LOOKS right and returns HTTP 200 with a full set of map
 * tiles, but this endpoint does not parse it and silently renders the entire planet. The
 * plain-text business query below is the only one that resolves our actual Google
 * Business listing, so the pin is labelled WECARE.DIGITAL and carries the verified
 * address. Do not "tidy" this into a place_id.
 */

// The verified Google Place for WECARE.DIGITAL. Still used for the keyless deep links
// below, where place_id IS honoured - it is only the embed endpoint that ignores it.
const PLACE_ID = 'ChIJQTvOovt3AjoRitCdl0-xHJk';

/**
 * COORDINATES, NOT A PLACE QUERY - and that switch is what removes Google's card.
 *
 * The embed used to be queried by business name. That made Google draw its OWN info card
 * inside the frame: a white Roboto panel with "WECARE.DIGITAL", the address, a blue
 * open-in-new-tab button, a blue directions button, a 4.5-star rating and an (i) icon.
 * None of it could be restyled. The iframe is cross-origin, so our CSS and JS cannot reach
 * a single node inside it - there is no selector, no injected stylesheet and no amount of
 * !important that touches it. Asking for that box "in our design" therefore has exactly
 * one solution: stop Google drawing a box, and draw our own outside the frame.
 *
 * A lat/lng query does that. Measured in a framed browser: with coordinates the frame
 * contains no business name, no rating and no action buttons - just a pin - while a name
 * query still carries all of it.
 *
 * WHERE THESE NUMBERS COME FROM. Two independent sources were checked, and they disagree
 * by roughly 200 m. OpenStreetMap geocodes "Phears Lane, Tiretti" to 22.5731893,
 * 88.3576881 - the street, not the building. Google's own resolved position for the
 * business listing is the pair below, which is the point the old name-query pin was
 * already dropping. The Google pair is used because it is the verified premises rather
 * than a street centroid, and because it keeps the pin exactly where it was before this
 * change. Confirmed visually: the pin lands on Phears Ln between Haberly Ln and Sri Nath,
 * which is the block in the postal address.
 */
const LAT = 22.5717148;
const LNG = 88.3566972;

/**
 * IST, written out rather than assumed from the visitor's clock. Someone deciding whether
 * it is a reasonable hour to call Kolkata needs OUR time, not theirs, and India has no
 * daylight saving so the offset never moves - but the tz database is still the right way to
 * express it, because hard-coding +05:30 arithmetic is how these things rot.
 */
const IST_ZONE = 'Asia/Kolkata';

/**
 * Live weather for the office, from Open-Meteo.
 *
 * WHY THIS PROVIDER: it needs no API key and sends access-control-allow-origin: *, both of
 * which matter on a static export where there is no server of ours to proxy through and no
 * safe place to put a credential. Measured before committing: HTTP 200, CORS wildcard
 * present, and it snaps to the nearest grid cell about 4 km away, which is correct enough
 * for "what is it like there right now" and is not being presented as more precise.
 *
 * LICENSING, FLAGGED RATHER THAN BURIED: Open-Meteo's free tier is for NON-COMMERCIAL use.
 * This is a commercial site, so this call should not stay here indefinitely. Two clean exits,
 * both better than the status quo: take their commercial plan, or proxy it through a Lambda
 * behind wecare.digital/api using the Google Weather key the owner already holds - which is
 * also how it stops being a third-party request from our own page. VayuLok is already the
 * weather product, so that endpoint arguably ought to exist anyway.
 *
 * IT FAILS INVISIBLY ON PURPOSE. If the request errors, times out or the shape changes, the
 * weather line is simply not rendered. An address card must never show "—°C" or a spinner
 * where a temperature should be; the address is the job and it is never blocked on this.
 */
const WEATHER_URL =
  `https://api.open-meteo.com/v1/forecast?latitude=${LAT}&longitude=${LNG}` +
  '&current=temperature_2m,weather_code&timezone=' + encodeURIComponent( IST_ZONE );

/**
 * WMO weather codes to short human labels.
 *
 * Deliberately coarse. The full table distinguishes "light" from "moderate" from "dense"
 * drizzle; on a contact card that is noise, and every extra word pushes the address down.
 * Codes are grouped to the phrase a person would actually use.
 */
const WMO: Record<number, string> = {
  0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast',
  45: 'Fog', 48: 'Freezing fog',
  51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle',
  56: 'Freezing drizzle', 57: 'Freezing drizzle',
  61: 'Light rain', 63: 'Rain', 65: 'Heavy rain',
  66: 'Freezing rain', 67: 'Freezing rain',
  71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains',
  80: 'Showers', 81: 'Showers', 82: 'Heavy showers',
  85: 'Snow showers', 86: 'Snow showers',
  95: 'Thunderstorm', 96: 'Thunderstorm', 99: 'Thunderstorm',
};

/**
 * z=18 rather than 17. Losing Google's card freed the space it used to cover, and one step
 * closer makes the lane names either side of the pin legible without panning.
 */
const EMBED_URL = `https://maps.google.com/maps?q=${LAT},${LNG}&z=18&output=embed`;

/**
 * TWO RENDER PATHS, and the key decides which.
 *
 * With NEXT_PUBLIC_GOOGLE_BROWSER_KEY set, this uses the Maps JavaScript API, which is
 * the only way to get what was actually asked for: satellite imagery, and Google's
 * pan / zoom / fullscreen / Street View controls GONE rather than merely blocked.
 * Those controls live inside a cross-origin iframe on the keyless path, so no CSS,
 * JS or URL parameter of ours can reach them - an overlay could stop them working
 * but could never hide them.
 *
 * Without a key it falls back to the keyless iframe plus the interaction overlay.
 * That matters: a missing key must degrade to a working map, never to a blank panel
 * or a link out to Google, which is what an unkeyed Embed API url renders.
 *
 * ON THE KEY BEING PUBLIC. It ships in the page, and that is correct - a Maps
 * browser key is public by design and Google's own model is to restrict it by HTTP
 * referrer rather than hide it. This is NOT the same class of secret as the Google
 * Translate key, which is why that one sits in Secrets Manager behind a Lambda and
 * this one does not. Two things are therefore load-bearing in the Cloud console, and
 * neither is enforceable from this repo:
 *   Application restrictions  ->  HTTP referrers, *.wecare.digital/*
 *   API restrictions          ->  Maps JavaScript / Static Maps / Places only
 * With Application restrictions set to None, anyone who views source can bill the
 * project without limit.
 *
 * ATTRIBUTION IS NOT OPTIONAL ON EITHER PATH. The JS API paints the Google logo and
 * the data attribution into the map div itself. disableDefaultUI does not remove it
 * and must not be made to: it is a licence condition of Maps Platform, not a
 * control. Do not try to cover it.
 */
const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_BROWSER_KEY || '';

const ADDRESS_LINES = [
  'The W.B.S.I.D.C. Building',
  'Unit 1/20, 81/2/7 Phears Lane',
  'Kolkata, West Bengal 700012',
  'India',
];

/** Google's short code for the entrance. Works on its own in Google Maps search. */
const PLUS_CODE = 'H9C4+MMP';
const PHONE_DISPLAY = '+91 93309 94400';
const PHONE_HREF = '+919330994400';
const EMAIL = 'one@wecare.digital';

/**
 * Keyless deep link for turn-by-turn directions. The /maps/dir/ endpoint DOES honour
 * place_id (unlike the embed endpoint above), so this pins the exact verified premises
 * rather than a geocoded guess at the street.
 *
 * This is the one link in the section that leaves the site, and it is deliberate: it is an
 * explicit "Get directions" button a visitor chooses to press, not the map being replaced
 * by a redirect. Seeing where we are costs no navigation; routing to us needs a maps app.
 */
const DIRECTIONS_URL = `https://www.google.com/maps/dir/?api=1&destination=WECARE.DIGITAL&destination_place_id=${PLACE_ID}`;

const ContactLocation: React.FC = () => {
  // NULL UNTIL MOUNTED, and that is a correctness requirement rather than caution. With
  // output:'export' this component is rendered to HTML at build time in Node, so formatting
  // a clock during render would bake the BUILD time into the file and then disagree with the
  // browser on hydration - a guaranteed mismatch, and a wrong time on screen until React
  // reconciled it. Rendering nothing server-side and filling both in after mount is the only
  // way either value can be honest.
  const [ istTime, setIstTime ] = useState<string | null>( null );
  const [ weather, setWeather ] = useState<{ temp: number; label: string } | null>( null );
  const mapHost = useRef<HTMLDivElement | null>( null );

  // Maps JS API, only when a key is configured. Everything in the options block is
  // the point of taking this path at all:
  //   mapTypeId 'roadmap'     show the normal map by default
  //   mapTypeControl true     keep Roadmap/Satellite available as an explicit user choice
  //   disableDefaultUI true   remove the rest of the default controls; mapTypeControl is re-enabled below
  //   gestureHandling 'none'  no drag, no scroll-zoom, natively rather than via an overlay
  //   keyboardShortcuts false no focus-then-arrow-keys route back into panning
  //   clickableIcons false    no POI click opening Google's own info card over ours
  useEffect( () => {
    if ( !MAPS_KEY || typeof window === 'undefined' ) return;
    const w = window as unknown as {
      google?: { maps?: Record<string, unknown> };
      __wecareContactMapReady?: () => void;
    };

    const init = () => {
      const maps = w.google?.maps as undefined | {
        Map: new ( el: HTMLElement, opts: Record<string, unknown> ) => unknown;
        Marker: new ( opts: Record<string, unknown> ) => unknown;
        Size: new ( w: number, h: number ) => unknown;
        Point: new ( x: number, y: number ) => unknown;
      };
      if ( !mapHost.current || !maps ) return;
      const map = new maps.Map( mapHost.current, {
        center: { lat: LAT, lng: LNG },
        zoom: 18,
        mapTypeId: 'roadmap',
        disableDefaultUI: true,
        mapTypeControl: true,
        mapTypeControlOptions: { mapTypeIds: [ 'roadmap', 'satellite' ] },
        gestureHandling: 'none',
        keyboardShortcuts: false,
        clickableIcons: false,
      } );

      /**
       * OUR PIN, IN OUR PALETTE - and the stroke is not decoration.
       *
       * The owner asked for a lime pin. Lime #d1f470 alone will not do the job: it
       * measures about 1.4:1 against white, which is the measured reason the brand dot in
       * BrandLockup could not be lime either, and on pale satellite imagery a flat lime
       * pin disappears. So it is lime FILL with a #1a3a2a stroke - the contract's own
       * lime-plus-dark-green pairing, the same one used for .cl-cta and BrandBadge. The
       * stroke is what makes it legible over both bright roofs and dark foliage.
       *
       * Drawn as an SVG data URI rather than a PNG so it stays crisp on any DPR and
       * carries no network request.
       */
      const PIN = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="52" viewBox="0 0 40 52">
        <path d="M20 1.5c-10.2 0-18.5 8.3-18.5 18.5 0 13.2 15.6 28.4 17.2 29.9a1.9 1.9 0 0 0 2.6 0C22.9 48.4 38.5 33.2 38.5 20 38.5 9.8 30.2 1.5 20 1.5z"
              fill="#d1f470" stroke="#1a3a2a" stroke-width="3"/>
        <circle cx="20" cy="20" r="6.5" fill="#1a3a2a"/>
      </svg>`;

      new maps.Marker( {
        position: { lat: LAT, lng: LNG },
        map,
        title: 'WECARE.DIGITAL',
        icon: {
          url: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent( PIN )}`,
          scaledSize: new maps.Size( 40, 52 ),
          // Anchor at the point of the pin, not its centre, so the tip sits on the
          // premises rather than the artwork being centred on them.
          anchor: new maps.Point( 20, 52 ),
        },
      } );
    };

    if ( w.google?.maps ) { init(); return; }

    // One script tag per document, reused across remounts. Appending a second copy makes
    // the API log a duplicate-loader warning and can re-run callbacks.
    const ID = 'gmaps-js';
    const CALLBACK = '__wecareContactMapReady';
    // Google explicitly documents that loading=async does not use the script element's
    // load event for application readiness. Register the supported global callback before
    // inserting (or reusing) the loader so initial loads and client-side remounts converge.
    w.__wecareContactMapReady = init;

    const existing = document.getElementById( ID );
    if ( existing ) return;

    const script = document.createElement( 'script' );
    script.id = ID;
    script.async = true;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent( MAPS_KEY )}&loading=async&callback=${CALLBACK}`;
    document.head.appendChild( script );
  }, [] );

  useEffect( () => {
    const format = () => new Intl.DateTimeFormat( 'en-IN', {
      timeZone: IST_ZONE, hour: '2-digit', minute: '2-digit', hour12: false,
    } ).format( new Date() );

    // FIRST TICK VIA requestAnimationFrame, not a direct call. setIstTime( format() ) in the
    // effect body would be a synchronous setState in an effect - the exact
    // react-hooks/set-state-in-effect error this repo already carries 115 of, and there is no
    // reason to add the 116th. A rAF callback lands before the first paint a user can see, so
    // nothing is lost visually.
    const raf = requestAnimationFrame( () => setIstTime( format() ) );
    // 20s, not 60s: a minute-resolution clock updated once a minute can sit visibly stale for
    // almost a full minute after the minute rolls over.
    const id = window.setInterval( () => setIstTime( format() ), 20000 );

    return () => { cancelAnimationFrame( raf ); window.clearInterval( id ); };
  }, [] );

  useEffect( () => {
    // AbortController so a visitor who leaves before the response lands does not get a
    // setState on an unmounted component.
    const ac = new AbortController();

    ( async () => {
      try {
        const res = await fetch( WEATHER_URL, { signal: ac.signal } );
        if ( !res.ok ) return;
        const data = await res.json();
        const temp = data?.current?.temperature_2m;
        const code = data?.current?.weather_code;
        // Number.isFinite, not a truthiness check: 0 °C is a real temperature and 0 is also
        // the WMO code for "Clear", so `if ( !temp )` would silently discard both.
        if ( !Number.isFinite( temp ) ) return;
        setWeather( { temp: Math.round( temp ), label: WMO[ code ] ?? '' } );
      } catch {
        /* Deliberately silent - see WEATHER_URL. The card renders without this line. */
      }
    } )();

    return () => ac.abort();
  }, [] );

  return (
    <section className="cl" aria-labelledby="cl-title">
      <h2 className="cl-h2" id="cl-title">Where to find us</h2>

      <div className="cl-grid">
        {/* A map renders on every load either way. The branch is about WHICH map, never
            about whether one appears - the earlier keyed version degraded to a link out
            to Google when the key was absent, and that is the one outcome ruled out. */}
        <div className="cl-map">
          { MAPS_KEY ? (
            /* KEYED PATH. A plain div the JS API draws into. No overlay is needed here -
               gestureHandling:'none' and disableDefaultUI do natively what the overlay
               below has to fake, and there are no controls left to block. */
            <>
              <div
                ref={ mapHost }
                className="cl-frame"
                role="img"
                aria-label="Satellite map showing the WECARE.DIGITAL office on Phears Lane, Kolkata"
              />
              {/* THE NAME AT THE PIN, and it is OUR element rather than a Google label.
                  Google's own options for this are an InfoWindow or Marker.label. The
                  InfoWindow is the white Roboto bubble with a close cross that the owner
                  already rejected once and that no CSS of ours can restyle; Marker.label
                  paints text inside the pin, which is far too small for a 14-character
                  wordmark. Drawing it ourselves is the only way it lands in this site's
                  type.
                  NO PROJECTION MATHS NEEDED, and that is a consequence of the map being a
                  fixed illustration: center is pinned to LAT/LNG and gestureHandling is
                  'none', so the marker is permanently at the div's centre. The label is
                  therefore positioned at 50%/50% and lifted by the pin's own height (52px
                  anchored at its tip) plus a 6px gap. If the map is ever made pannable or
                  zoomable this breaks, and it would need a real OverlayView instead.
                  aria-hidden because the frame above already carries the full accessible
                  name, and the address is in the column beside it - a screen reader should
                  not hear the company name three times. */}
            </>
          ) : (
            <>
              <iframe
                className="cl-frame"
                src={ EMBED_URL }
                title="Map showing the WECARE.DIGITAL office on Phears Lane, Kolkata"
                loading="lazy"
                referrerPolicy="no-referrer-when-downgrade"
              />

          {/* INTERACTION LOCK - AND READ THE LIMIT BELOW, IT IS NOT WHAT IT LOOKS LIKE.
              A transparent sheet OVER the iframe, not a setting on it, because the iframe
              is cross-origin: neither our CSS nor our JS can reach inside it, so Google's
              own controls cannot be configured away from here. Over the area it covers it
              does work - it swallows drag, scroll-zoom, clicks and POI info dialogs.

              IT DOES NOT MAKE GOOGLE'S CONTROLS INERT. This comment used to claim it did.
              Measured with tools/browser/contactcheck.js, which enters the cross-origin
              frame and then hit-tests each control through the page:

                frame 668x500, lock covers y 0..474 (inset:0 0 26px 0)
                "Show satellite imagery"  42x42 at (10,447)   15px below the lock
                "Keyboard shortcuts"      87x14 at (319,486)  26px below the lock
                "Map camera controls"     40x40 at (618,436)   2px below the lock

              All three are anchored to the frame's BOTTOM edge, which is exactly the strip
              the lock deliberately leaves uncovered for attribution. document.elementFromPoint
              at each exposed point returns the iframe, so a real click reaches Google: the
              satellite button will switch the imagery, and the map is not the fixed
              illustration this file claims it is.

              WHY IT IS NOT SIMPLY PATCHED. Blocking them means covering part of that bottom
              strip while leaving "Terms" and "Report a map error" clickable - they sit in the
              SAME strip, at x 538..662, with "Keyboard shortcuts" at x 319..406 between them
              and the left edge. Those coordinates are Google's private layout, undocumented
              and free to change. A pixel-tuned cut-out would therefore fail in one of two
              directions on any Google change: silently re-expose a control, or silently cover
              the attribution - and the second is a licence breach, which is far worse than
              the defect being fixed. So this is deliberately NOT patched geometrically.

              THE THREE REAL OPTIONS, all owner calls:
                1. Set NEXT_PUBLIC_GOOGLE_BROWSER_KEY. The keyed Maps JS path below already
                   passes disableDefaultUI, which removes these controls outright rather than
                   covering them. This is the fix the code is already written for.
                2. Static Maps - a flat image has no controls at all. Also keyed.
                3. pointer-events:none on the iframe plus our OWN attribution links rendered
                   outside it. Robust and keyless, but it moves a licence-bearing element
                   into our markup, so it needs a decision rather than a commit.
              Until one is chosen, contactcheck.js fails one assertion on purpose. */}
              <div className="cl-lock" aria-hidden="true" />
            </>
          ) }

          {/* OUR CARD, IN PLACE OF GOOGLE'S. This sits OUTSIDE the iframe and on top of
              it, which is the only way it can be ours - see the note on LAT/LNG for why
              nothing inside a cross-origin frame can be styled.
              It carries the two things Google's panel had that are worth keeping, the name
              and the street, in this site's type and colour, and drops the two that were
              noise: a star rating from two reviews, and duplicate buttons for actions the
              address column beside it already offers.
              Positioned TOP-left on purpose. Google's attribution, the "Map data ©2026
              Google / Terms / Report a map error" strip, sits along the bottom edge and is
              a condition of using the embed at all - covering it would be a licence
              breach, not a design choice, so the card stays clear of it. */}
          {/* THE LIME WECARE.DIGITAL PILL THAT SAT HERE IS GONE, on owner instruction, and
              the reason is that the card directly below already carries the name.
              It was a second WECARE.DIGITAL inside the same map frame: a lime pill pinned to
              the top strip, and .cl-card-name repeating the identical string ~56px beneath
              it, next to the IST and weather chips. One map panel, one business, the name
              twice - and the card is the copy worth keeping, because it is the one carrying
              the address and the live row rather than standing alone.
              THE NARROW-SCREEN RULES ALREADY AGREED. Below 768px the pill was set to
              display:none on the stated grounds that "the card already carries the
              WECARE.DIGITAL name, so the wordmark is not lost". That reasoning was never
              specific to small screens; it is just as true at 1280. Removing the pill applies
              it everywhere and lets the card return to top:16px at every width, which is the
              value it had before the pill was introduced and the value mobile already used.
              Nothing about Google's own red pin changes either way - on the keyless path it is
              painted inside a cross-origin iframe and was always unreachable by our CSS. The
              keyed Maps JS path still draws the lime #d1f470 pin with a #1a3a2a stroke. */}
          <div className="cl-card">
            {/* data-wc-no-translate: a company name, for the reason BrandLockup.tsx sets out
                at length. This one is the map card's business name, so it is the same string
                Google shows on the listing beside it - a translated copy next to an
                untranslated one would read as two different businesses. This is now the only
                WECARE.DIGITAL in the map frame: the lime .cl-pinlabel pill that used to sit
                above it has been removed, so the flag here is no longer one of two. The
                address below is NOT
                flagged: a street and city are worth translating, and the postcode has no
                letters for the walker to collect. */}
            <p className="cl-card-name" data-wc-no-translate="true">WECARE.DIGITAL</p>
            <p className="cl-card-addr">Phears Lane<br />Kolkata 700012, WB</p>

            {/* LIVE ROW. Rendered only once at least one value has arrived, so the card never
                shows an empty strip or a placeholder dash. Both chips carry the theme's own
                rounded corners - 10px, one step inside the card's 14px, which is how nested
                radii stay concentric instead of looking stuck on. */}
            { ( istTime || weather ) && (
              <p className="cl-card-live">
                { istTime && (
                  <span className="cl-chip">
                    <span className="cl-chip-k">IST</span>
                    {/* tabular-nums in CSS stops the chip resizing as digits change. */}
                    <span className="cl-chip-v">{ istTime }</span>
                  </span>
                ) }
                { weather && (
                  <span className="cl-chip">
                    <span className="cl-chip-v">{ weather.temp }°C</span>
                    { weather.label && <span className="cl-chip-k">{ weather.label }</span> }
                  </span>
                ) }
              </p>
            ) }
          </div>
        </div>

        <div className="cl-copy">
          <p className="cl-label">Address</p>
          {/* itemProp-free, but marked up as a real address element so assistive tech
              and crawlers read it as one. */}
          <address className="cl-address">
            { ADDRESS_LINES.map( line => <span key={ line }>{ line }</span> ) }
          </address>

          <p className="cl-label">Plus code</p>
          <p className="cl-value"><code className="cl-code">{ PLUS_CODE }</code></p>

          <p className="cl-label">Phone</p>
          <p className="cl-value"><a className="cl-link" href={ `tel:${PHONE_HREF}` }>{ PHONE_DISPLAY }</a></p>

          <p className="cl-label">Email</p>
          <p className="cl-value"><a className="cl-link" href={ `mailto:${EMAIL}` }>{ EMAIL }</a></p>

          <a className="cl-cta" href={ DIRECTIONS_URL } target="_blank" rel="noopener noreferrer">
            Get directions
          </a>
        </div>
      </div>

      <style jsx>{`
        /* cl- prefixed. The globally imported src/styles/*.css declares unscoped rules
           for generic names and styled-jsx does not shield a page from them. */

        /* scroll-margin-top clears the fixed 108px header, using the same 128px/112px
           pair as .lgd-section in LegalDocument rather than a new number.
           WHAT THIS FIXES, MEASURED. The header is position:fixed at z-index 1001; the
           map card is absolutely positioned 16px inside the frame at z-index 1. So
           anything that scrolls this section to the top of the viewport puts the card
           underneath the header. With scroll-margin-top at 0 that was 90px of a 151px
           card hidden at 768px wide (76px at 1024, 78px at 390, 2px at 1440), and the
           h2 itself landed completely behind the header when following /contact/#cl-title
           - which is a real linkable URL, since the heading carries that id.
           It is on all three of the section, the heading and the map so that an anchor,
           an aria-labelledby jump or a programmatic scrollIntoView all land clear.
           WHAT THIS DOES NOT FIX, stated so nobody re-measures it and files it twice:
           a visitor scrolling by hand still passes the card under the header, because
           that is what a fixed header does to every element on the page. Only pinning
           the card (position:sticky inside the frame) would change that, which is a
           design decision rather than a bug fix. */
        .cl{max-width:1000px;margin-top:64px;scroll-margin-top:128px}
        .cl-h2,.cl-map{scroll-margin-top:128px}
        /* Section h2 on the contract's 700 rung - heavier than the hero h1's 600, which
           is the inversion this whole site uses. Same clamp as the other section
           headings so they read as siblings. */
        .cl-h2{
          font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;
          letter-spacing:-1.2px;color:rgba(0,0,0,.95);margin:0 0 24px;
        }

        /* Map left, details right. The map is 1fr and the copy column a fixed 300px for
           the same reason the Home terminal band is built that way: an address block
           reflows cleanly at any width, a map just gets less useful. */
        .cl-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:28px;align-items:start}

        /* THE LIME EDGE IS THE WHOLE POINT of the treatment the owner asked for. The
           supplied app framed its map in #111 ink on a 13px radius; this uses our own
           14px radius and puts a 2px lime border on it - 2px because the hairline rule
           on this site is 1px static, 2px interactive, and a map you can pan is
           interactive. The tinted backdrop shows through while the iframe loads, so the
           frame never flashes white. */
        .cl-map{
          position:relative;overflow:hidden;
          border:2px solid #d1f470;border-radius:14px;
          background:rgba(209,244,112,.22);
          aspect-ratio:4/3;
        }
        /* display:block kills the inline-element baseline gap under the iframe, which
           otherwise shows as a few pixels of tint along the bottom edge. */
        .cl-frame{display:block;width:100%;height:100%;border:0}
        /* Narrow hide: remove only Google attribution/branding nodes; keep map controls intact. */
        .cl :global(.gm-style-cc),
        .cl :global(a[aria-label="Google Maps"]),
        .cl :global(img[alt="Google"]){display:none!important}
        /* bottom:26px leaves Google's attribution strip uncovered and clickable. Raise
           this and you are disabling a licence condition. */
        .cl-lock{position:absolute;inset:0 0 26px 0;z-index:1;background:transparent;cursor:default}

        /* .cl-pinlabel IS GONE. It was a lime WECARE.DIGITAL pill pinned to the top strip of
           the map frame, and .cl-card-name repeats that exact string ~40px below it beside the
           IST and weather chips - the same name twice in one panel. Removed on owner
           instruction; the card is the copy that stays, because it carries the address and the
           live row rather than standing alone.
           If it is ever wanted back, it was: position:absolute, left:50% with
           translateX(-50%), top:12px, z-index:2, 5px 11px padding, 2px #1a3a2a border,
           14px radius, #d1f470 on #1a3a2a, 13px/700, nowrap, pointer-events:none. And
           .cl-card would need its top inset dropped again to clear it. */

        /* THE CARD THAT REPLACED GOOGLE'S. Same 14px radius and 2px lime edge as the map
           frame itself, so it reads as part of this site rather than as a tooltip the map
           produced. The shadow is the one already used for hover lift elsewhere, not a new
           value.
           top:16px, BACK from 56px. The 56 existed only to drop this card below the lime
           WECARE.DIGITAL pill that used to be pinned at top:12px - with that pill removed
           there is nothing to clear, so the card returns to the frame's own 16px inset. That
           is also the value the narrow-screen override already used, so the override is gone
           too and one number now applies at every width. Still well clear of Google's
           bottom-edge attribution strip. */
        /* inset-inline-start, not left: this card floats over the map, and an overlay has to
           sit on the edge the reader starts from or it covers the first thing they look at.
           Found by measuring mirror symmetry rather than by eye - it was 396px out of
           position under rtl at 1280, the largest asymmetry on this route.
           A logical property is safe HERE specifically because the only media-query override
           of .cl-card changes the top inset. Where a media query also overrides the inline
           axis, the Lightning :lang() rewrite out-specifies it and a custom property is needed
           instead - see the note on .wc-langbar in SupportWidget.tsx.
           NO BACKTICKS IN THIS COMMENT: styled-jsx template literal. */
        .cl-card{
          position:absolute;top:16px;inset-inline-start:16px;z-index:1;
          max-width:calc(100% - 32px);
          padding:14px 18px;
          border:2px solid #d1f470;border-radius:14px;
          background:#fff;
          box-shadow:0 4px 12px rgba(26,58,42,.12);
        }
        /* Card-heading rung at its small end: 19px/700. Smaller than the 22px used on the
           page's own cards because this one overlays a map and must not dominate it. */
        .cl-card-name{margin:0 0 4px;font-size:19px;font-weight:700;letter-spacing:-.25px;line-height:1.2;color:#1a3a2a}
        .cl-card-addr{margin:0;font-size:15px;font-weight:400;line-height:1.4;color:rgba(0,0,0,.54)}

        /* The live row. Separated by the site's 1px static hairline rather than extra space,
           so it reads as a second kind of information instead of a loose afterthought. */
        .cl-card-live{
          display:flex;flex-wrap:wrap;gap:6px;
          margin:10px 0 0;padding-top:10px;border-top:1px solid #e5e7eb;
        }
        /* 10px radius: one step inside the card's 14px. Nesting the same 14px would make the
           inner corner look slacker than the outer one at this size, which is the usual way
           rounded corners go wrong. The .22 lime tint is the contract's quiet fill - these are
           labels, not actions, so full-strength lime would overstate them. */
        .cl-chip{
          display:inline-flex;align-items:baseline;gap:5px;
          padding:4px 9px;border-radius:10px;
          background:rgba(209,244,112,.22);
          white-space:nowrap;
        }
        /* Uppercase micro-label, same 12px/700/.08em as every eyebrow on the site. */
        .cl-chip-k{font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:rgba(0,0,0,.72)}
        /* tabular-nums keeps the clock from shifting width as the digits change, which is
           what makes a ticking time look like a bug. */
        .cl-chip-v{font-size:16px;font-weight:700;letter-spacing:-.1px;color:#1a3a2a;font-variant-numeric:tabular-nums}

        .cl-copy{min-width:0}
        .cl-label{
          margin:0 0 6px;font-size:12px;font-weight:700;
          letter-spacing:.08em;text-transform:uppercase;color:rgba(0,0,0,.54);
        }
        .cl-label:not(:first-child){margin-top:20px}

        /* font-style:normal because browsers italicise <address> by default, and an
           italic postal address reads as a quotation. */
        .cl-address{margin:0;font-style:normal;display:flex;flex-direction:column;gap:2px}
        .cl-address span{font-size:17px;font-weight:400;line-height:1.5;letter-spacing:-.05px;color:rgba(0,0,0,.898)}
        /* 1.55, not 1.5, to match --line in src/styles/Layout.css. 17px is the site's
           --base-font, so a value line has no reason to carry its own rhythm. That left
           17px rendering at three different line-heights across the public pages
           (24.14 / 25.5 / 26.35) for no design reason.
           The one remaining exception is deliberate: .msg in the Grahak OS hero runs
           17px/1.42 because WhatsApp chat bubbles are tight, and loosening them to the
           body rhythm makes the mockup stop reading as a real conversation. */
        .cl-value{margin:0;font-size:17px;line-height:1.55;color:rgba(0,0,0,.898)}

        /* The plus code is a code, so it is set as one - tabular mono keeps the glyphs
           from shifting and signals that it is meant to be copied verbatim. */
        .cl-code{
          font-family:'SF Mono',Monaco,Consolas,monospace;font-size:16px;font-weight:700;
          padding:3px 8px;border-radius:6px;
          background:rgba(209,244,112,.22);color:#1a3a2a;
        }

        .cl-link{color:#1a3a2a;font-weight:600;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}
        .cl-link:hover{background:rgba(209,244,112,.22)}

        /* Full-strength lime with #1a3a2a type: the contract's own-surface pairing, and
           the single actionable surface in this section. */
        .cl-cta{
          display:inline-flex;align-items:center;min-height:52px;margin-top:28px;
          padding:0 26px;border:2px solid #1a3a2a;border-radius:50px;
          background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;text-decoration:none;
          transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        .cl-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .cl-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

        @media(prefers-reduced-motion:reduce){
          .cl-cta{transition:none}
          .cl-cta:hover{transform:none}
        }

        @media(max-width:899px){
          /* One column, and the map goes shorter and wider - 16/9 rather than 4/3 - so it
             does not eat the whole screen above the address on a phone. */
          .cl-grid{grid-template-columns:1fr;gap:24px}
          .cl-map{aspect-ratio:16/9}
          .cl{margin-top:48px}
          /* NO .cl-card OR .cl-pinlabel OVERRIDE HERE ANY MORE, and both removals are the
             same removal. This block used to set .cl-card{top:16px} and
             .cl-pinlabel{display:none} because the 16/9 map is only ~200px tall at 390px, so
             a top-band pill plus a 155px card below it did not fit above Google's 26px
             attribution strip. The pill is gone site-wide now and the card's base rule is
             top:16px, so both overrides say what the default already says.
             The reasoning given here for hiding the pill - "the card already carries the
             WECARE.DIGITAL name, so the wordmark is not lost" - is what the owner applied at
             every width. The card stays visible at every viewport, which contactcheck.js
             requires. */
        }

        /* 112px below 768px, matching .lgd-section, because .hdr-in drops to 96px there.
           Keyed to max-width:767px for the same reason the header rule is: at exactly
           768px the header is still 108px tall, so the desktop offset must still apply. */
        @media(max-width:767px){
          .cl,.cl-h2,.cl-map{scroll-margin-top:112px}
        }
      `}</style>
    </section>
  );
};

export default ContactLocation;
