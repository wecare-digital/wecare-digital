import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

/**
 * VayuLok LIVE content, appended BELOW the rotating-word hero on /vayulok/.
 *
 * WHAT THIS IS. The REAL, live-wired version of docs/mocks/vayulok-live-mock.html.
 * The mock is a VISUAL reference only: its layout and styled-jsx design tokens are
 * ported verbatim here, but every static sample value is replaced with LIVE data
 * fetched CLIENT-SIDE from Google's India-SKU APIs plus the Maps JavaScript API.
 *
 * THE MOCK'S "never call these from a browser" STANCE IS A MOCK CONSTRAINT, NOT THIS
 * PAGE'S. The mock header says weather/air/pollen are server-side web services
 * and uses static placeholders. For the real page the owner wants LIVE data, and these
 * Google APIs ARE called client-side from the browser with the referrer-restricted
 * browser key - exactly as the shipped src/components/ContactLocation.tsx already calls
 * Open-Meteo client-side. So this component follows ContactLocation's proven approach.
 *
 * THE KEY. Read ONLY from process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY, exactly as
 * ContactLocation.tsx does. With output:'export', that value is inlined into a JS chunk
 * at build time - never into the prerendered HTML, because it is only read inside a
 * useEffect. No key literal appears anywhere in this file. A Maps BROWSER key is public
 * by design and Google restricts it by HTTP referrer (*.wecare.digital/*); the live map
 * therefore only renders on a deployed *.wecare.digital origin, never in CI or sandbox.
 *
 * HONEST DEGRADATION. When the key is absent, this renders the hero (owned by the page)
 * plus the content shell WITHOUT the map and WITHOUT live panels, and fires ZERO network
 * calls. No spinner, no "--" placeholder. Each API fetch uses AbortController + cleanup,
 * `if(!res.ok) return`, Number.isFinite guards (0 is a real value), and silent catch, so
 * any failed call simply omits its fields rather than showing broken state. The keyless
 * map area is a LOCAL .vl-live-map-placeholder - plain text over a muted panel, no src and
 * no remote asset - so this path contacts no third party at all, not even Google.
 *
 * DEFAULT-ON MAP VISUALS. The keyed map paints (a) Google's continuous AQI heatmap tiles
 * (UAQI_RED_GREEN) and (b) a code-rendered atmospheric layer: soft cloud masses, wind
 * streamlines and a storm vortex whose density/speed are driven by the selected place's LIVE
 * Google Weather values (cloud cover, rain/storm probability and wind). The atmosphere is SVG/
 * CSS, not a static image and not an invented Google tile endpoint. On the KEYLESS path no
 * ImageMapType or atmosphere layer is mounted and zero third-party calls fire. The PM2.5
 * deck.gl dot overlay stays independent and is still only built when PM2.5 is selected.
 *
 * SELF-STYLING via styled-jsx with a vl-live- scope. styled-jsx only attaches its scoping
 * class to markup it can statically see, so every element stays INLINE in this component's
 * return tree. No bare html/body/* selectors; the mock's data-vl-preview-only block and
 * .vl-preview-shell are PREVIEW-ONLY and are NOT ported.
 *
 * ATTRIBUTION. There is no CSS targeting .gm-style-cc, a[href*="google"] or
 * img[alt="Google"], and every overlay stays inset from the map's bottom corners, where
 * Google paints its logo and legal notices (Maps Platform ToS).
 */

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY || '';

// Selected-place marker uses Google's canonical Material Symbols Outlined "location_on"
 // glyph (source: google/material-design-icons), presented on the same lime/green circle
 // as the site's icon system. This replaces the oversized bespoke teardrop marker.
const LOCATION_MARKER_ICON = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent( `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36"><circle cx="18" cy="18" r="17" fill="#d1f470"/><svg x="6" y="6" width="24" height="24" viewBox="0 -960 960 960"><path fill="#1a3a2a" d="M480-480q33 0 56.5-23.5T560-560q0-33-23.5-56.5T480-640q-33 0-56.5 23.5T400-560q0 33 23.5 56.5T480-480Zm0 294q122-112 181-203.5T720-552q0-109-69.5-178.5T480-800q-101 0-170.5 69.5T240-552q0 71 59 162.5T480-186Zm0 106Q319-217 239.5-334.5T160-552q0-150 96.5-239T480-880q127 0 223.5 89T800-552q0 100-79.5 217.5T480-80Zm0-480Z"/></svg></svg>` )}`;

// AQI / PM2.5 spatial dots follow the approved VayuLok no-red palette.
// Real values still determine the band; only the presentation ramp is brand-scoped.
const DOT_FILL_RGBA: Record<Sev, [ number, number, number, number ]> = {
  good: [ 61, 163, 90, 210 ],     // #3da35a
  sat: [ 209, 244, 112, 210 ],    // #d1f470
  mod: [ 232, 197, 71, 210 ],     // #e8c547
  poor: [ 201, 138, 46, 210 ],    // #c98a2e
  worst: [ 201, 138, 46, 210 ],   // warm cap; intentionally no red
};
const DOT_LINE_RGBA: [ number, number, number, number ] = [ 255, 255, 255, 230 ];

// PM2.5 (µg/m³) -> severity band, mirroring the AQI ramp's no-red bands so a PM2.5 dot
// shares the same five-step palette as the AQI dot. Real values only; callers drop NaN.
function pm25Severity( pm25: number ): Sev {
  if ( pm25 <= 30 ) return 'good';
  if ( pm25 <= 60 ) return 'sat';
  if ( pm25 <= 90 ) return 'mod';
  if ( pm25 <= 120 ) return 'poor';
  return 'worst';
}

// Global map: do not re-introduce a lat/lng restriction here because destination search
// is worldwide. Manual pan/zoom gestures are disabled; only an explicit place selection
// is allowed to move the camera.

// Place-autocomplete debounce. 120ms is a deliberately snappy value: it keeps ONE
// Autocomplete Data API request per settled keystroke (so a fast typist does not spam the
// SKU) while feeling immediate rather than the previous 300ms lag. The session-token reuse
// (autocompleteTokenRef) behavior is unchanged; only the settle delay is shorter.
const SEARCH_DEBOUNCE_MS = 120;

// Continuous AQI heatmap TILE overlay (the organic, blob-shaped pollution cloud from the
// reference). The AQI "Heatmap" switch paints Google's Air Quality heatmapTiles onto the
// map's overlayMapTypes as a google.maps.ImageMapType, replacing the old discrete deck.gl
// dot grid for the AQI layer. Tile endpoint shape (zoom 0-16, 256px tiles):
//   https://airquality.googleapis.com/v1/mapTypes/{mapType}/heatmapTiles/{zoom}/{x}/{y}?key=...
// The browser MAPS_KEY is appended as a query param - the same key every other Air Quality
// call in this component already uses.
//
// SCOPED RED EXCEPTION: UAQI_RED_GREEN is the Universal AQI red-green palette, the most
// representative continuous global AQI heatmap and the closest match to the reference
// image's green -> yellow -> orange -> red cloud. These tiles are rendered server-side by
// Google and MAY contain red for high-pollution areas. That red is DELIBERATELY allowed,
// but ONLY inside these tile IMAGES on the map. The rest of the page/card (legend ramp,
// gauge, pollutant rows, hourly history, health recommendations, every component CSS color)
// stays on the approved no-red palette (#c98a2e -> #e8c547 -> #d1f470 -> #3da35a) and never
// introduces a red hex. The SCOPED RED EXCEPTION also covers the WEATHER/STORM tiles below:
// Google's server-rendered radar/cloud imagery MAY contain colour (including red) inside the
// tile IMAGES; that red lives ONLY in the remote tiles, never in this component's CSS/markup.
const AQI_HEATMAP_MAP_TYPE = 'UAQI_RED_GREEN';
const PM25_HEATMAP_MAP_TYPE = 'PM25_INDIGO_PERSIAN';
const AQI_HEATMAP_TILE_BASE = 'https://airquality.googleapis.com/v1/mapTypes';

// The storm look is rendered locally as SVG/CSS over the live map and is driven by Google
// Weather values already fetched for the selected place. Google Weather map tiles currently
// cover only documented US/EU precipitation products, so there is intentionally no fabricated
// global `tile.googleapis.com/.../weather` URL here.
// Neutral map camera; no place is selected until the visitor acts.
interface PlaceState {
  name: string;
  addr: string;
  lat: number;
  lng: number;
  // Retain the resolved Google Place ID so a future server-side Geocoding v4
  // SearchDestinations relay can enrich discrete destinations without re-searching.
  placeId?: string;
  // Honest, optional Google Place metadata surfaced in the left card. Each is written to
  // state ONLY when the Places API actually returned it, so the card never shows an
  // invented fact or a placeholder (see metaFromGooglePlace / the left-card guards).
  primaryType?: string;
  types?: string[];
  rating?: number;
  userRatingCount?: number;
  websiteURI?: string;
  summary?: string;
  viewport?: { north: number; south: number; east: number; west: number };
  regionCode?: string;
}

// The extra Place fields requested on the keyed search/select + map-click paths, on top of
// the display fields. Fetched ONLY on those existing keyed paths - never unconditionally -
// so honest degradation (no key => no fetch) is preserved.
const PLACE_META_FIELDS = [
  'types',
  'primaryTypeDisplayName',
  'rating',
  'userRatingCount',
  'websiteURI',
  'editorialSummary',
  'viewport',
] as const;

/* The shape of a resolved google.maps.places.Place once fetchFields has run. Mirrors the
   Places JS API: every metadata field is optional and only present when Google returned
   it. We never fabricate; absence simply means that line does not render. */
interface GooglePlaceLike {
  fetchFields?: ( req: { fields: string[] } ) => Promise<void>;
  id?: string;
  displayName?: string;
  formattedAddress?: string;
  location?: { lat?: () => number; lng?: () => number };
  addressComponents?: { types?: string[]; shortText?: string }[];
  types?: string[];
  primaryTypeDisplayName?: string;
  rating?: number;
  userRatingCount?: number;
  websiteURI?: string;
  editorialSummary?: string;
  viewport?: { toJSON?: () => { north: number; south: number; east: number; west: number } };
}

/* Pull the honest metadata subset off a resolved Google Place. Returns only the fields
   that are genuinely present (finite numbers, non-empty strings, real booleans); every
   other field is left undefined so the left card renders nothing for it. */
function metaFromGooglePlace( p: GooglePlaceLike ): Partial<PlaceState> {
  const meta: Partial<PlaceState> = {};
  const primaryType = humanisePlaceType( p.primaryTypeDisplayName );
  if ( primaryType ) meta.primaryType = primaryType;
  const types = Array.isArray( p.types )
    ? p.types.map( humanisePlaceType ).filter( ( t ): t is string => Boolean( t ) )
    : [];
  if ( types.length ) meta.types = Array.from( new Set( types ) ).slice( 0, 3 );
  if ( Number.isFinite( p.rating ) ) meta.rating = p.rating;
  if ( Number.isFinite( p.userRatingCount ) ) meta.userRatingCount = p.userRatingCount;
  if ( typeof p.websiteURI === 'string' && p.websiteURI ) meta.websiteURI = p.websiteURI;
  const summary = typeof p.editorialSummary === 'string' ? p.editorialSummary.trim() : '';
  if ( summary ) meta.summary = summary;
  const viewport = p.viewport?.toJSON?.();
  if ( viewport && [ viewport.north, viewport.south, viewport.east, viewport.west ].every( Number.isFinite ) ) meta.viewport = viewport;
  const country = p.addressComponents?.find( component => component.types?.includes( 'country' ) )?.shortText;
  if ( typeof country === 'string' && country.trim() ) meta.regionCode = country.trim().toUpperCase();
  return meta;
}

// Google place-type tokens arrive as snake_case machine strings (e.g. 'tourist_attraction').
// primaryTypeDisplayName is already human-readable. Normalise both into Title Case words,
// dropping empties, so attribute lines read like prose rather than API enums.
function humanisePlaceType( raw: unknown ): string | undefined {
  if ( typeof raw !== 'string' ) return undefined;
  const cleaned = raw.replaceAll( '_', ' ' ).trim();
  if ( !cleaned ) return undefined;
  return cleaned.replace( /\b\w/g, c => c.toUpperCase() );
}

interface SearchResult {
  name: string;
  addr: string;
  place?: PlaceState;
  prediction?: {
    toPlace?: () => GooglePlaceLike;
  };
}

const DEFAULT_PLACE: PlaceState = {
  // Default local view: Lumpyngngad, Shillong. This is the Meghalaya PCB monitoring
  // area the owner selected as the initial VayuLok destination. Search/recent-place
  // selection can replace it; live Weather/Air requests use these coordinates.
  name: 'Lumpyngngad',
  addr: 'Shillong, Meghalaya',
  lat: 25.5586,
  lng: 91.8985,
  regionCode: 'IN',
};

// OWNER OVERRIDE (reference screenshot, 2026-10-06): the selected place now uses the STANDARD
// RED Google marker (default google.maps.Marker pin). The prior no-red brand SVG pin is retired
// per decisions.md Decision 2; the recenter/marker effect creates a default-icon Marker.

// GEOMETRY ON THE REPO PALETTE, ported verbatim from the mock's map styles.
const MAP_STYLES = [
  { elementType: 'geometry', stylers: [ { color: '#fafafa' } ] },
  { elementType: 'labels.text.fill', stylers: [ { color: '#1a3a2a' } ] },
  { elementType: 'labels.text.stroke', stylers: [ { color: '#ffffff' }, { weight: 3 } ] },

  // Keep the map unmistakably a street map: road names and locality labels stay visible.
  { featureType: 'road', elementType: 'geometry', stylers: [ { color: '#ffffff' } ] },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: [ { color: '#e5e7eb' } ] },
  { featureType: 'road', elementType: 'labels', stylers: [ { visibility: 'on' } ] },
  { featureType: 'road', elementType: 'labels.text.fill', stylers: [ { color: '#1a3a2a' } ] },
  { featureType: 'road.local', elementType: 'labels', stylers: [ { visibility: 'on' } ] },
  { featureType: 'road.arterial', elementType: 'labels', stylers: [ { visibility: 'on' } ] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [ { color: '#ffffff' } ] },
  { featureType: 'road.highway', elementType: 'labels', stylers: [ { visibility: 'on' } ] },
  { featureType: 'administrative.locality', elementType: 'labels', stylers: [ { visibility: 'on' } ] },
  { featureType: 'administrative.neighborhood', elementType: 'labels', stylers: [ { visibility: 'on' } ] },

  { featureType: 'poi', elementType: 'labels', stylers: [ { visibility: 'off' } ] },
  { featureType: 'poi.park', elementType: 'geometry', stylers: [ { color: '#f5fde0' } ] },
  { featureType: 'transit', stylers: [ { visibility: 'off' } ] },
  { featureType: 'water', elementType: 'geometry', stylers: [ { color: '#e8eeea' } ] },
];

/* ---- AQI category + severity-form mapping ------------------------------------------
   India AQI (CPCB) bands. Severity is encoded by FORM (dot/bar class) AND the category
   WORD in text, never colour alone (WCAG 1.4.1). NO red anywhere - the ramp walks dark
   green -> lime -> amber, matching the mock's severity ramp. */
type Sev = 'good' | 'sat' | 'mod' | 'poor' | 'worst';

function aqiCategory( aqi: number ): { word: string; sev: Sev } {
  if ( aqi <= 50 ) return { word: 'Good', sev: 'good' };
  if ( aqi <= 100 ) return { word: 'Satisfactory', sev: 'sat' };
  if ( aqi <= 200 ) return { word: 'Moderate', sev: 'mod' };
  if ( aqi <= 300 ) return { word: 'Poor', sev: 'poor' };
  if ( aqi <= 400 ) return { word: 'Very Poor', sev: 'worst' };
  return { word: 'Severe', sev: 'worst' };
}

/* The "Past air quality" history bar's AQI-ramp class. This reuses the SAME band logic as the
   live dot / pollutant tone (aqiCategory) so the history reads with the identical
   good -> sat -> mod -> poor -> worst ramp rather than a flat lime->green gradient. No new
   thresholds are invented here; the single source of truth stays aqiCategory. */
function aqiBarClass( aqi: number ): string {
  return `vl-live-history-bar-${aqiCategory( aqi ).sev}`;
}

/* Human-readable label for the selected history range, used in the chart's aria-label so a
   screen reader hears "last 24 hours" rather than a raw hour count. */
function historyRangeLabel( hours: 24 | 168 | 720 ): string {
  if ( hours === 24 ) return 'last 24 hours';
  if ( hours === 168 ) return 'last 7 days';
  return 'last 30 days';
}

/* A plain-English "current status" word for the PM2.5 result block, derived from the SAME
   severity band the dot and category already use (never a new scale). The mockup's
   "Elevated" sits in this ramp between the clean and the hazardous ends. */
function statusWord( sev: Sev ): string {
  switch ( sev ) {
    case 'good': return 'Clean';
    case 'sat': return 'Acceptable';
    case 'mod': return 'Elevated';
    case 'poor': return 'High';
    default: return 'Hazardous';
  }
}

/* ---- Health recommendation personas -------------------------------------------------
   Google Air Quality currentConditions returns tailored guidance for seven supported
   populations. These definitions contain LABEL + API KEY + Google Material Symbol only:
   recommendation copy always comes from Google's response, never from static fallback text. */
type HealthRecommendationKey =
  | 'generalPopulation'
  | 'elderly'
  | 'lungDiseasePopulation'
  | 'heartDiseasePopulation'
  | 'athletes'
  | 'pregnantWomen'
  | 'children';

type HealthPersonaIcon =
  | 'general'
  | 'elderly'
  | 'respiratory'
  | 'heart'
  | 'athletes'
  | 'pregnant'
  | 'children';

interface HealthPersonaDefinition {
  id: string;
  label: string;
  apiKey: HealthRecommendationKey;
  icon: HealthPersonaIcon;
}

/* Local paths from Google's Material Symbols Outlined set. Keeping the SVG paths local avoids
   a runtime icon-font dependency while preserving Google's icon language across the Air card. */
const MATERIAL_SYMBOL_PATHS: Record<
  HealthPersonaIcon | 'info' | 'switches' | 'close' | 'air' | 'schedule' | 'location' | 'chevronLeft' | 'chevronRight',
  string
> = {
  info: 'M453-280h60v-240h-60v240Zm50.5-323.2q9.5-9.2 9.5-22.8 0-14.45-9.48-24.22-9.48-9.78-23.5-9.78t-23.52 9.78Q447-640.45 447-626q0 13.6 9.48 22.8 9.48 9.2 23.5 9.2t23.52-9.2ZM480.27-80q-82.74 0-155.5-31.5Q252-143 197.5-197.5t-86-127.34Q80-397.68 80-480.5t31.5-155.66Q143-709 197.5-763t127.34-85.5Q397.68-880 480.5-880t155.66 31.5Q709-817 763-763t85.5 127Q880-563 880-480.27q0 82.74-31.5 155.5Q817-252 763-197.68q-54 54.31-127 86Q563-80 480.27-80Zm.23-60Q622-140 721-239.5t99-241Q820-622 721.19-721T480-820q-141 0-240.5 98.81T140-480q0 141 99.5 240.5t241 99.5Zm-.5-340Z',
  switches: 'M270-289q-80 0-135-54.5T80-479q0-81 54.5-135.5T270-669q51 0 90 22t65 63h350q44 0 74.5 30.5T880-479q0 44-30.5 74.5T775-374H425q-26 41-65 63t-90 22Zm3-190Zm180 45h322q20 0 32.5-12.5T820-479q0-20-12.5-32.5T775-524H453q4 10 5.5 22t1.5 23q0 11-1.5 23t-5.5 22Zm-90.5 47.5Q400-424 400-479t-37.5-92.5Q325-609 270-609t-92.5 37.5Q140-534 140-479t37.5 92.5Q215-349 270-349t92.5-37.5Z',
  close: 'M256-214 214-256l224-224-224-224 42-42 224 224 224-224 42 42-224 224 224 224-42 42-224-224-224 224Z',
  chevronLeft: 'M560-240 320-480l240-240 56 56-184 184 184 184-56 56Z',
  chevronRight: 'M504-480 320-664l56-56 240 240-240 240-56-56 184-184Z',
  air: 'M460-160q-50 0-85-35t-35-85h80q0 17 11.5 28.5T460-240q17 0 28.5-11.5T500-280q0-17-11.5-28.5T460-320H80v-80h380q50 0 85 35t35 85q0 50-35 85t-85 35ZM80-560v-80h540q26 0 43-17t17-43q0-26-17-43t-43-17q-26 0-43 17t-17 43h-80q0-59 40.5-99.5T620-840q59 0 99.5 40.5T760-700q0 59-40.5 99.5T620-560H80Zm660 320v-80q26 0 43-17t17-43q0-26-17-43t-43-17H80v-80h660q59 0 99.5 40.5T880-380q0 59-40.5 99.5T740-240Z',
  schedule: 'm612-292 56-56-148-148v-184h-80v216l172 172ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-400Zm0 320q133 0 226.5-93.5T800-480q0-133-93.5-226.5T480-800q-133 0-226.5 93.5T160-480q0 133 93.5 226.5T480-160Z',
  location: 'M480-480q33 0 56.5-23.5T560-560q0-33-23.5-56.5T480-640q-33 0-56.5 23.5T400-560q0 33 23.5 56.5T480-480Zm0 294q122-112 181-203.5T720-552q0-109-69.5-178.5T480-800q-101 0-170.5 69.5T240-552q0 71 59 162.5T480-186Zm0 106Q319-217 239.5-334.5T160-552q0-150 96.5-239T480-880q127 0 223.5 89T800-552q0 100-79.5 217.5T480-80Zm0-480Z',
  general: 'M420-340h120v-100h100v-120H540v-100H420v100H320v120h100v100Zm60 260q-139-35-229.5-159.5T160-516v-244l320-120 320 120v244q0 152-90.5 276.5T480-80Zm0-84q104-33 172-132t68-220v-189l-240-90-240 90v189q0 121 68 220t172 132Zm0-316Z',
  elderly: 'm320-40-48-36 104-139-8-191q-2-52 5.5-109.5T397-617l-97 56v111h-60v-146l167-96q17-10 32.5-15t29.5-5q27 0 48.5 21t41.5 66q20 46 59 75.5t94 46.5q7-4 13.5-5.5T739-510q23 0 42 18.5t19 41.5v410h-30v-410q0-12-9-21t-21-9q-12 0-21 9t-9 21v30h-30v-33q-42-11-87.5-42T521-568q-12 34-18.5 75t-4.5 73l97 137v243h-60v-219l-85-95-10 154L320-40Zm218-714q-30 0-51.5-21.5T465-827q0-30 21.5-51.5T538-900q30 0 51.5 21.5T611-827q0 30-21.5 51.5T538-754Z',
  respiratory: 'M190-120q-46 0-78-32t-32-78v-185l108-279q12-31 40.07-48.5t60.82-17.5q42.11 0 71.61 29.57T390-659v39h-60v-39q0-17.19-12.83-29.1-12.82-11.9-29.92-11.9-14.25 0-26.25 6.5T244-674L140-405v175q0 21.25 14.38 35.62Q168.75-180 190-180h140q21.25 0 35.63-14.38Q380-208.75 380-230v-70h60v70q0 46-32.08 78-32.09 32-77.92 32H190Zm580 0H630q-45.83 0-77.92-32Q520-184 520-230v-70h60v70q0 21.25 14.38 35.62Q608.75-180 630-180h140q21.25 0 35.63-14.38Q820-208.75 820-230v-175L716-674q-5-13-17-19.5t-26-6.5q-17 0-30 11.9-13 11.91-13 29.1v39h-60v-39q0-41.86 29.52-71.43Q629.03-760 671.2-760q32.8 0 60.8 17.5t40 48.5l108 279v185q0 46-32.08 78-32.09 32-77.92 32ZM334-456Zm292 0Zm-146-62L376-414l-42-42 116-116v-308h60v308l116 116-42 42-104-104Z',
  heart: 'M290-840q57 0 105.5 27t84.5 78q42-54 89-79.5T670-840q89 0 149.5 60.5T880-629q0 15-1.5 29.5T873-570h-62q5-15 7-29.5t2-29.5q0-66-42-108.5T670-780q-51 0-95 31.5T504-660h-49q-26-56-70-88t-95-32q-66 0-108 42.5T140-629q0 15 2 29.5t7 29.5H87q-4-15-5.5-29.5T80-629q0-90 60.5-150.5T290-840Zm-98 450h78q38 42 89.5 91.5T480-186q69-63 120-112.5t89-91.5h79q-42 49-102 108.5T521-144l-41 37-41-37q-85-78-145-137.5T192-390Zm250 60q9 0 16-5.5t10-14.5l61-181 46 68q5 6 11 9.5t14 3.5h310v-60H617l-72-106q-5-7-12-10t-15-3q-9 0-16.5 5.5T491-609l-60 181-47-69q-5-6-10.5-9.5T360-510H50v60h292l72 107q5 7 12.5 10t15.5 3Zm38-153Z',
  athletes: 'M520-40v-240l-84-80-40 176-276-56 16-80 192 40 64-324-72 28v136h-80v-188l158-68q35-15 51.5-19.5T480-720q21 0 39 11t29 29l40 64q26 42 70.5 69T760-520v80q-66 0-123.5-27.5T540-540l-24 120 84 80v300h-80Zm20-700q-33 0-56.5-23.5T460-820q0-33 23.5-56.5T540-900q33 0 56.5 23.5T620-820q0 33-23.5 56.5T540-740Z',
  pregnant: 'M400-80v-200h-80v-280q0-50 35-85t85-35q50 0 85 35t35 85q36 15 58 48t22 72v160H520v200H400Zm40-640q-33 0-56.5-23.5T360-800q0-33 23.5-56.5T440-880q33 0 56.5 23.5T520-800q0 33-23.5 56.5T440-720Z',
  children: 'M580-490q-21 0-35.5-14.5T530-540q0-21 14.5-35.5T580-590q21 0 35.5 14.5T630-540q0 21-14.5 35.5T580-490Zm-200 0q-21 0-35.5-14.5T330-540q0-21 14.5-35.5T380-590q21 0 35.5 14.5T430-540q0 21-14.5 35.5T380-490Zm100 210q-60 0-108.5-33T300-400h360q-23 54-71.5 87T480-280Zm0 160q-75 0-140.5-28.5t-114-77q-48.5-48.5-77-114T120-480q0-75 28.5-140.5t77-114q48.5-48.5 114-77T480-840q75 0 140.5 28.5t114 77q48.5 48.5 77 114T840-480q0 75-28.5 140.5t-77 114q-48.5 48.5-114 77T480-120Zm0-80q116 0 198-82t82-198q0-116-82-198t-198-82h-12q-6 0-12 2-6 6-8 13t-2 15q0 21 14.5 35.5T496-680q9 0 16.5-3t15.5-3q12 0 20 9t8 21q0 23-21.5 29.5T496-620q-45 0-77.5-32.5T386-730v-6q0-3 1-8-83 30-135 101t-52 163q0 116 82 198t198 82Zm0-280Z',
};

const HEALTH_PERSONAS: HealthPersonaDefinition[] = [
  { id: 'general', label: 'General population', apiKey: 'generalPopulation', icon: 'general' },
  { id: 'elderly', label: 'Elderly', apiKey: 'elderly', icon: 'elderly' },
  { id: 'respiratory', label: 'Lung disease', apiKey: 'lungDiseasePopulation', icon: 'respiratory' },
  { id: 'heart', label: 'Heart disease', apiKey: 'heartDiseasePopulation', icon: 'heart' },
  { id: 'athletes', label: 'Athletes', apiKey: 'athletes', icon: 'athletes' },
  { id: 'pregnant', label: 'Pregnant women', apiKey: 'pregnantWomen', icon: 'pregnant' },
  { id: 'children', label: 'Children', apiKey: 'children', icon: 'children' },
];

function compactAirInfo( value?: string, maxChars = 92 ): string | undefined {
  if ( typeof value !== 'string' ) return undefined;
  const clean = value.replace( /\s+/g, ' ' ).trim();
  if ( !clean ) return undefined;
  if ( clean.length <= maxChars ) return clean;
  const cut = clean.slice( 0, maxChars + 1 );
  const wordBoundary = cut.lastIndexOf( ' ' );
  return `${cut.slice( 0, wordBoundary > 72 ? wordBoundary : maxChars ).replace( /[,:;\s]+$/, '' )}…`;
}

// Pollen category 0-5 UPI -> word (Google's universal pollen index).
function pollenCategory( idx: number ): string {
  if ( idx <= 0 ) return 'None';
  if ( idx === 1 ) return 'Very Low';
  if ( idx === 2 ) return 'Low';
  if ( idx === 3 ) return 'Moderate';
  if ( idx === 4 ) return 'High';
  return 'Very High';
}

/* ---- live data shapes ---------------------------------------------------------------
   Every field is optional: a value only enters state once it actually arrived, so the
   markup renders only the fields that are present and never a placeholder. */
interface AirIndexInfo {
  code: string;
  displayName?: string;
  aqi: number;
  aqiDisplay?: string;
  category?: string;
  dominantPollutant?: string;
  regionCode?: string;
  color?: { red?: number; green?: number; blue?: number };
}

interface AirState {
  aqi: number;
  word: string;
  sev: Sev;
  indexName?: string;
  indexCode?: string;
  aqiDisplay?: string;
  regionCode?: string;
  indexes?: AirIndexInfo[];
  universalIndex?: AirIndexInfo;
  localIndex?: AirIndexInfo;
  dominant?: string;
  pollutants: {
    code: string;
    label: string;
    fullName?: string;
    value: number;
    unit: string;
    sources?: string;
    effects?: string;
  }[];
  healthRecommendations?: Partial<Record<HealthRecommendationKey, string>>;
  advisory?: string;
  updatedAt?: string;
}

interface LocationTimeState {
  timeZoneId: string;
  timeZoneName: string;
  shortLabel: string;
  source: 'default' | 'google';
}

const DEFAULT_LOCATION_TIME: LocationTimeState = {
  timeZoneId: 'Asia/Kolkata',
  timeZoneName: 'India Standard Time',
  shortLabel: 'IST',
  source: 'default',
};
interface WeatherState {
  temp?: number;
  feelsLike?: number;
  humidity?: number;
  windSpeed?: number;
  windUnit?: string;
  windDir?: string;
  windGust?: number;
  rainMm?: number;
  rainProb?: number;
  stormProb?: number;
  uv?: number;
  visibilityKm?: number;
  pressureHpa?: number;
  dewPoint?: number;
  heatIndex?: number;
  wetBulb?: number;
  cloudCover?: number;
  condition?: string;
  currentTime?: string;
}
interface WeatherHour {
  time: number;
  temp?: number;
  feelsLike?: number;
  rainProb?: number;
  rainMm?: number;
  stormProb?: number;
  uv?: number;
  windSpeed?: number;
  windUnit?: string;
  windDir?: string;
  condition?: string;
  icon?: string;
}
interface WeatherDay {
  time: number;
  label: string;
  dateLabel: string;
  min?: number;
  max?: number;
  rainProb?: number;
  condition?: string;
  icon?: string;
  sunrise?: string;
  sunset?: string;
}
interface AirPoint {
  time: number;
  aqi: number;
  word: string;
  pm25?: number;
  dominant?: string;
  indexCode?: string;
  localAqi?: number;
  universalAqi?: number;
  healthRecommendations?: Partial<Record<HealthRecommendationKey, string>>;
  pollutants?: {
    code: string;
    label?: string;
    fullName?: string;
    value: number;
    unit: string;
    sources?: string;
    effects?: string;
  }[];
}
interface WeatherAlertRow {
  id: string;
  title: string;
  description?: string;
  area?: string;
  severity?: string;
  urgency?: string;
  expires?: string;
}
interface PollenRow { label: string; index: number; word: string; day: string; }

const COMPASS = [ 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW' ];
function windDirection( deg: number ): string {
  return COMPASS[ Math.round( deg / 45 ) % 8 ];
}
function windDirectionDegrees( dir?: string ): number {
  const i = COMPASS.indexOf( String( dir || '' ).toUpperCase() );
  return i >= 0 ? i * 45 : 225;
}

function worldPixel( lat: number, lng: number, zoom: number ): { x: number; y: number } {
  const scale = 256 * Math.pow( 2, zoom );
  const sin = Math.max( -.9999, Math.min( .9999, Math.sin( lat * Math.PI / 180 ) ) );
  return {
    x: scale * ( .5 + lng / 360 ),
    y: scale * ( .5 - Math.log( ( 1 + sin ) / ( 1 - sin ) ) / ( 4 * Math.PI ) ),
  };
}

function clamp( value: number, min: number, max: number ): number {
  return Math.min( max, Math.max( min, value ) );
}
// The Air Quality API returns concentration units as long SCREAMING_SNAKE enums
// (MICROGRAMS_PER_CUBIC_METER, PARTS_PER_BILLION, ...). Rendered verbatim they blow
// out the value column and collide with the category word. Map them to short symbols.
function concUnitLabel( unit?: string ): string {
  switch ( unit ) {
    case 'MICROGRAMS_PER_CUBIC_METER': return '\u00B5g/m\u00B3';
    case 'PARTS_PER_BILLION': return 'ppb';
    case 'PARTS_PER_MILLION': return 'ppm';
    case 'MILLIGRAMS_PER_CUBIC_METER': return 'mg/m\u00B3';
    case 'NANOGRAMS_PER_CUBIC_METER': return 'ng/m\u00B3';
    default: return unit || '';
  }
}

// Short display label for the wind-speed unit the Weather API returns on wind.speed.unit
// (e.g. KILOMETERS_PER_HOUR, MILES_PER_HOUR). Fall back to km/h under unitsSystem=METRIC.
function windUnitLabel( unit?: string ): string {
  switch ( unit ) {
    case 'MILES_PER_HOUR': return 'mph';
    case 'METERS_PER_SECOND': return 'm/s';
    case 'KILOMETERS_PER_HOUR': return 'km/h';
    default: return 'km/h';
  }
}

function n( value: unknown ): number {
  const out = Number( value );
  return Number.isFinite( out ) ? out : NaN;
}

function weatherHourFromApi( row: Record<string, any> ): WeatherHour | null {
  const time = new Date( row?.interval?.startTime || row?.dateTime || 0 ).getTime();
  if ( !Number.isFinite( time ) ) return null;
  const out: WeatherHour = { time };
  const temp = n( row?.temperature?.degrees );
  const feels = n( row?.feelsLikeTemperature?.degrees );
  const rain = n( row?.precipitation?.probability?.percent );
  const rainMm = n( row?.precipitation?.qpf?.quantity );
  const storm = n( row?.thunderstormProbability );
  const uv = n( row?.uvIndex );
  const windSpeed = n( row?.wind?.speed?.value );
  const windDeg = n( row?.wind?.direction?.degrees );
  if ( Number.isFinite( temp ) ) out.temp = Math.round( temp );
  if ( Number.isFinite( feels ) ) out.feelsLike = Math.round( feels );
  if ( Number.isFinite( rain ) ) out.rainProb = Math.round( rain );
  if ( Number.isFinite( rainMm ) ) out.rainMm = rainMm;
  if ( Number.isFinite( storm ) ) out.stormProb = Math.round( storm );
  if ( Number.isFinite( uv ) ) out.uv = Math.round( uv );
  if ( Number.isFinite( windSpeed ) ) out.windSpeed = Math.round( windSpeed );
  if ( Number.isFinite( windSpeed ) ) out.windUnit = windUnitLabel( row?.wind?.speed?.unit );
  if ( Number.isFinite( windDeg ) ) out.windDir = windDirection( windDeg );
  if ( typeof row?.weatherCondition?.description?.text === 'string' ) out.condition = row.weatherCondition.description.text;
  if ( typeof row?.weatherCondition?.iconBaseUri === 'string' ) out.icon = row.weatherCondition.iconBaseUri;
  return out;
}

function airPointFromApi( row: Record<string, any> ): AirPoint | null {
  const time = new Date( row?.dateTime || row?.period?.startTime || row?.interval?.startTime || 0 ).getTime();
  if ( !Number.isFinite( time ) ) return null;
  const indexes = Array.isArray( row?.indexes ) ? row.indexes : [];
  const local = indexes.find( ( i: any ) => i?.code && i.code !== 'uaqi' && Number.isFinite( i.aqi ) );
  const universal = indexes.find( ( i: any ) => i?.code === 'uaqi' && Number.isFinite( i.aqi ) );
  const idx = local || universal || indexes.find( ( i: any ) => Number.isFinite( i?.aqi ) );
  const aqi = n( idx?.aqi );
  if ( !Number.isFinite( aqi ) ) return null;
  const pollutantRows = ( Array.isArray( row?.pollutants ) ? row.pollutants : [] )
    .map( ( p: any ) => ( {
      code: String( p?.code || '' ),
      ...( typeof p?.displayName === 'string' && p.displayName.trim() ? { label: p.displayName.trim() } : {} ),
      ...( typeof p?.fullName === 'string' && p.fullName.trim() ? { fullName: p.fullName.trim() } : {} ),
      value: n( p?.concentration?.value ),
      unit: concUnitLabel( p?.concentration?.units ),
      ...( typeof p?.additionalInfo?.sources === 'string' && p.additionalInfo.sources.trim() ? { sources: p.additionalInfo.sources.trim() } : {} ),
      ...( typeof p?.additionalInfo?.effects === 'string' && p.additionalInfo.effects.trim() ? { effects: p.additionalInfo.effects.trim() } : {} ),
    } ) )
    .filter( p => Boolean( p.code ) && Number.isFinite( p.value ) );
  const pm = pollutantRows.find( p => p.code === 'pm25' );
  const healthRecommendations = parseHealthRecommendations( row?.healthRecommendations );
  return {
    time,
    aqi: Math.round( aqi ),
    word: typeof idx?.category === 'string' && idx.category.trim() ? idx.category.trim() : aqiCategory( aqi ).word,
    ...( pm ? { pm25: pm.value } : {} ),
    ...( typeof idx?.dominantPollutant === 'string' ? { dominant: idx.dominantPollutant } : {} ),
    ...( typeof idx?.code === 'string' ? { indexCode: idx.code } : {} ),
    ...( local && Number.isFinite( local.aqi ) ? { localAqi: Math.round( local.aqi ) } : {} ),
    ...( universal && Number.isFinite( universal.aqi ) ? { universalAqi: Math.round( universal.aqi ) } : {} ),
    ...( healthRecommendations ? { healthRecommendations } : {} ),
    ...( pollutantRows.length ? { pollutants: pollutantRows } : {} ),
  };
}

function hourLabel( ms: number ): string {
  return new Intl.DateTimeFormat( 'en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric' } ).format( new Date( ms ) );
}

/* Friendly labels for the Google pollutant codes, shared by the pollutant rows and the
   dominant-pollutant chip so both read consistently (e.g. "pm25" -> "PM2.5"). */
const POLLUTANT_LABELS: Record<string, string> = {
  pm25: 'PM2.5', pm10: 'PM10', no2: 'NO\u2082', o3: 'O\u2083', co: 'CO', so2: 'SO\u2082',
};

/* Resolve a dominant pollutant code to the same friendly label the rows use. Prefer a
   label already carried on a matching pollutant row, then the shared map, then fall back
   to the raw code so an unknown dominant pollutant is still surfaced rather than hidden. */
function dominantPollutantLabel( code: string, pollutants: AirState['pollutants'] ): string {
  const fromRow = pollutants.find( p => p.code === code )?.label;
  return fromRow || POLLUTANT_LABELS[ code ] || code;
}

function parseHealthRecommendations( raw: unknown ): AirState['healthRecommendations'] | undefined {
  if ( !raw || typeof raw !== 'object' ) return undefined;
  const source = raw as Record<string, unknown>;
  const out: Partial<Record<HealthRecommendationKey, string>> = {};
  HEALTH_PERSONAS.forEach( persona => {
    const value = source[ persona.apiKey ];
    if ( typeof value === 'string' && value.trim() ) out[ persona.apiKey ] = value.trim();
  } );
  return Object.keys( out ).length ? out : undefined;
}

function timeZoneShortLabel( timeZoneId: string, timeZoneName: string ): string {
  if ( /Asia\/(Kolkata|Calcutta)/i.test( timeZoneId ) ) return 'IST';
  try {
    const part = new Intl.DateTimeFormat( 'en-US', {
      timeZone: timeZoneId,
      timeZoneName: 'short',
    } ).formatToParts( new Date() ).find( row => row.type === 'timeZoneName' )?.value;
    if ( part ) return part;
  } catch { /* invalid/unsupported zone -> use Google's long name below */ }
  return timeZoneName || 'Local';
}

function formatLocationClock( now: number, timeZoneId: string ): string {
  try {
    return new Intl.DateTimeFormat( 'en-IN', {
      timeZone: timeZoneId,
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    } ).format( new Date( now ) );
  } catch {
    return new Intl.DateTimeFormat( 'en-IN', {
      timeZone: DEFAULT_LOCATION_TIME.timeZoneId,
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    } ).format( new Date( now ) );
  }
}

function formatHistoryStamp( value: number, timeZoneId: string, zoneLabel: string ): string {
  try {
    const parts = new Intl.DateTimeFormat( 'en-CA', {
      timeZone: timeZoneId,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    } ).formatToParts( new Date( value ) );
    const pick = ( type: Intl.DateTimeFormatPartTypes ) => parts.find( part => part.type === type )?.value || '';
    return `${pick( 'year' )}-${pick( 'month' )}-${pick( 'day' )} ${pick( 'hour' )}:${pick( 'minute' )} ${zoneLabel}`;
  } catch {
    return `${new Date( value ).toISOString().slice( 0, 16 ).replace( 'T', ' ' )} UTC`;
  }
}

function formatHistoryPointLabel( value: number, timeZoneId: string, zoneLabel: string ): string {
  try {
    const label = new Intl.DateTimeFormat( 'en-IN', {
      timeZone: timeZoneId,
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    } ).format( new Date( value ) );
    return `${label} ${zoneLabel}`;
  } catch {
    return `${new Date( value ).toISOString().slice( 5, 16 ).replace( 'T', ' ' )} UTC`;
  }
}

/* Parse a currentConditions:lookup payload into the LEFT-card AirState (AQI value +
   category word + severity + pollutant rows + advisory). Returns null when no finite AQI
   arrived, so a point that fails to parse is DROPPED, never fabricated. Shared by the
   layer-activation center-point fetch; the grid points reuse airPointFromApi instead. */
function airStateFromApiData( data: Record<string, any> | null | undefined ): AirState | null {
  const rawIndexes: Record<string, any>[] = Array.isArray( data?.indexes ) ? data.indexes : [];
  const indexes: AirIndexInfo[] = rawIndexes
    .filter( i => typeof i?.code === 'string' && Number.isFinite( i?.aqi ) )
    .map( i => ( {
      code: i.code,
      aqi: i.aqi,
      ...( typeof i.displayName === 'string' && i.displayName.trim() ? { displayName: i.displayName.trim() } : {} ),
      ...( typeof i.aqiDisplay === 'string' && i.aqiDisplay.trim() ? { aqiDisplay: i.aqiDisplay.trim() } : {} ),
      ...( typeof i.category === 'string' && i.category.trim() ? { category: i.category.trim() } : {} ),
      ...( typeof i.dominantPollutant === 'string' && i.dominantPollutant ? { dominantPollutant: i.dominantPollutant } : {} ),
      ...( typeof i.regionCode === 'string' && i.regionCode ? { regionCode: i.regionCode } : {} ),
      ...( i.color && typeof i.color === 'object' ? { color: i.color } : {} ),
    } ) );
  const localIndex = indexes.find( i => i.code !== 'uaqi' );
  const universalIndex = indexes.find( i => i.code === 'uaqi' );
  const idx = localIndex || universalIndex || indexes[ 0 ];
  if ( !idx || !Number.isFinite( idx.aqi ) ) return null;
  const aqi = idx.aqi;
  const cat = aqiCategory( aqi );
  const pollutants: AirState['pollutants'] = [];
  ( data?.pollutants || [] ).forEach( ( p: {
    code?: string;
    displayName?: string;
    fullName?: string;
    concentration?: { value?: number; units?: string };
    additionalInfo?: { sources?: string; effects?: string };
  } ) => {
    const label = p.code ? ( p.displayName || POLLUTANT_LABELS[ p.code ] ) : undefined;
    const v = p.concentration?.value;
    if ( label && Number.isFinite( v ) ) {
      pollutants.push( {
        code: p.code as string,
        label,
        ...( typeof p.fullName === 'string' && p.fullName.trim() ? { fullName: p.fullName.trim() } : {} ),
        value: v as number,
        unit: concUnitLabel( p.concentration?.units ),
        ...( typeof p.additionalInfo?.sources === 'string' && p.additionalInfo.sources ? { sources: p.additionalInfo.sources } : {} ),
        ...( typeof p.additionalInfo?.effects === 'string' && p.additionalInfo.effects ? { effects: p.additionalInfo.effects } : {} ),
      } );
    }
  } );
  const healthRecommendations = parseHealthRecommendations( data?.healthRecommendations );
  const advisory = healthRecommendations?.generalPopulation;
  return {
    aqi,
    word: idx.category || cat.word,
    sev: cat.sev,
    ...( idx.displayName ? { indexName: idx.displayName } : {} ),
    indexCode: idx.code,
    ...( idx.aqiDisplay ? { aqiDisplay: idx.aqiDisplay } : {} ),
    ...( typeof data?.regionCode === 'string' && data.regionCode ? { regionCode: data.regionCode } : {} ),
    indexes,
    ...( universalIndex ? { universalIndex } : {} ),
    ...( localIndex ? { localIndex } : {} ),
    dominant: idx.dominantPollutant || undefined,
    pollutants,
    ...( healthRecommendations ? { healthRecommendations } : {} ),
    advisory,
    updatedAt: typeof data?.dateTime === 'string' ? data.dateTime : undefined,
  };
}

/* The request body shared by the center-point and grid air fetches - identical shape to
   the former single-point fetchAir so dots carry the same real currentConditions values. */
function localAqiOverride( regionCode?: string ): Record<string, unknown> {
  return regionCode === 'IN'
    ? { customLocalAqis: [ { regionCode: 'IN', aqi: 'ind_cpcb' } ] }
    : {};
}

function relativeAgeLabel( value?: string | number ): { label: string; stale: boolean } {
  if ( value === undefined || value === null ) return { label: 'Current', stale: false };
  const ms = typeof value === 'number' ? value : new Date( value ).getTime();
  if ( !Number.isFinite( ms ) ) return { label: 'Current', stale: false };
  const mins = Math.max( 0, Math.floor( ( Date.now() - ms ) / 60_000 ) );
  if ( mins < 1 ) return { label: 'Updated just now', stale: false };
  if ( mins < 60 ) return { label: `Updated ${mins} min ago`, stale: mins >= 30 };
  const hours = Math.floor( mins / 60 );
  return { label: `Updated ${hours} hr${hours === 1 ? '' : 's'} ago`, stale: true };
}

function bestOutsideWindow( weatherHours: WeatherHour[], airHours: AirPoint[] ): { label: string; note: string } | null {
  if ( weatherHours.length < 2 ) return null;
  const scored = weatherHours.slice( 0, 24 ).map( ( w, i ) => {
    const a = airHours.find( p => Math.abs( p.time - w.time ) < 45 * 60 * 1000 ) || airHours[ i ];
    let score = 100;
    if ( Number.isFinite( w.rainProb ) ) score -= ( w.rainProb as number ) * .45;
    if ( Number.isFinite( w.stormProb ) ) score -= ( w.stormProb as number ) * .65;
    if ( Number.isFinite( w.uv ) && ( w.uv as number ) > 5 ) score -= ( ( w.uv as number ) - 5 ) * 5;
    if ( Number.isFinite( w.temp ) ) {
      if ( ( w.temp as number ) > 34 ) score -= ( ( w.temp as number ) - 34 ) * 5;
      if ( ( w.temp as number ) < 15 ) score -= ( 15 - ( w.temp as number ) ) * 2;
    }
    if ( a && Number.isFinite( a.aqi ) && a.aqi > 50 ) score -= ( a.aqi - 50 ) * .22;
    return { w, a, score };
  } );
  let best: { start: typeof scored[number]; end: typeof scored[number]; score: number } | null = null;
  for ( let i = 0; i < scored.length - 1; i++ ) {
    const pairScore = ( scored[ i ].score + scored[ i + 1 ].score ) / 2;
    if ( !best || pairScore > best.score ) best = { start: scored[ i ], end: scored[ i + 1 ], score: pairScore };
  }
  if ( !best ) return null;
  const end = new Date( best.end.w.time + 60 * 60 * 1000 ).getTime();
  const notes: string[] = [];
  if ( Number.isFinite( best.start.w.temp ) ) notes.push( String( best.start.w.temp ) + '°C' );
  if ( Number.isFinite( best.start.w.rainProb ) ) notes.push( String( best.start.w.rainProb ) + '% rain' );
  if ( best.start.a ) notes.push( 'AQI ' + String( best.start.a.aqi ) );
  if ( Number.isFinite( best.start.w.uv ) ) notes.push( 'UV ' + String( best.start.w.uv ) );
  return { label: hourLabel( best.start.w.time ) + '–' + hourLabel( end ), note: notes.join( ' · ' ) || 'Best upcoming outdoor window' };
}

const RECENT_PLACES_KEY = 'vayulok_recent_places_v2';

function recentPlaces(): PlaceState[] {
  if ( typeof window === 'undefined' ) return [];
  try {
    const rows = JSON.parse( window.localStorage.getItem( RECENT_PLACES_KEY ) || '[]' );
    return Array.isArray( rows ) ? rows.slice( 0, 5 ) : [];
  } catch {
    return [];
  }
}

function rememberPlace( place: PlaceState ) {
  if ( typeof window === 'undefined' ) return;
  try {
    const key = `${place.lat.toFixed( 4 )},${place.lng.toFixed( 4 )}`;
    const rows = recentPlaces().filter( p => `${p.lat.toFixed( 4 )},${p.lng.toFixed( 4 )}` !== key );
    rows.unshift( { name: place.name, addr: place.addr, lat: place.lat, lng: place.lng } );
    window.localStorage.setItem( RECENT_PLACES_KEY, JSON.stringify( rows.slice( 0, 5 ) ) );
  } catch { /* storage can be unavailable */ }
}

const VayuLokLive: React.FC = () => {
  // Load the owner-selected local destination immediately so the map and live panels
  // are useful on first paint; search/recent-place selection replaces this destination.
  const [ place, setPlace ] = useState<PlaceState>( DEFAULT_PLACE );
  const [ hasSelection, setHasSelection ] = useState( true );
  const [ detailTab, setDetailTab ] = useState<'air' | 'weather'>( 'air' );
  const [ mapReady, setMapReady ] = useState( false );
  const [ mapFailed, setMapFailed ] = useState( false );
  const [ searchStatus, setSearchStatus ] = useState<'idle' | 'searching' | 'no-results' | 'unavailable'>( 'idle' );

  const [ air, setAir ] = useState<AirState | null>( null );
  const [ weather, setWeather ] = useState<WeatherState | null>( null );
  const [ pollen, setPollen ] = useState<PollenRow[] | null>( null );
  const [ weatherHourly, setWeatherHourly ] = useState<WeatherHour[]>( [] );
  const [ weatherHistory, setWeatherHistory ] = useState<WeatherHour[]>( [] );
  const [ weatherDaily, setWeatherDaily ] = useState<WeatherDay[]>( [] );
  const [ weatherAlerts, setWeatherAlerts ] = useState<WeatherAlertRow[]>( [] );
  const [ airForecast, setAirForecast ] = useState<AirPoint[]>( [] );
  const [ airForecastHours, setAirForecastHours ] = useState<24 | 48 | 96>( 24 );
  const [ airForecastInspectIdx, setAirForecastInspectIdx ] = useState( 0 );
  const [ airHistory, setAirHistory ] = useState<AirPoint[]>( [] );
  // Default to the 168-hour (7-day) window so the Hourly History chart spans ~a week. The
  // history fetch effect keys on this value and only fetches on the keyed path (no key =>
  // no fetch => airHistory stays [], and the chart renders its honest empty shell).
  const [ historyRange, setHistoryRange ] = useState<24 | 168 | 720>( 168 );
  const [ historyLoading, setHistoryLoading ] = useState( false );
  const [ dataLoading, setDataLoading ] = useState( false );
  const [ coreError, setCoreError ] = useState( false );
  const [ refreshNonce, setRefreshNonce ] = useState( 0 );
  const [ coreFetchedAt, setCoreFetchedAt ] = useState<number | null>( null );
  const [ mapCandidate, setMapCandidate ] = useState<PlaceState | null>( null );
  const [ addressDescriptor, setAddressDescriptor ] = useState( '' );
  const [ locationTime, setLocationTime ] = useState<LocationTimeState>( DEFAULT_LOCATION_TIME );
  const [ clockNow, setClockNow ] = useState( () => Date.now() );

  // Search combobox state.
  const [ query, setQuery ] = useState( '' );
  const [ results, setResults ] = useState<SearchResult[]>( [] );
  const [ open, setOpen ] = useState( false );
  const [ active, setActive ] = useState( -1 );

  // Which air-quality layer is active. Defaults to 'AQI' so the continuous AQI heatmap TILE
  // overlay paints by DEFAULT once the keyed map is ready (the keyed + map-ready guard in the
  // layer effect still gates attachment, so a keyless/not-ready map creates NOTHING). The
  // Heatmap switch (aria-checked={layer==='AQI'}) therefore reads ON by default and still
  // turns the overlay OFF. Selecting a layer both toggles the map air-quality layer AND swaps
  // the environmental RESULT content shown in the LEFT card (AQI result vs PM2.5-focused).
  const [ heatmapMetric, setHeatmapMetric ] = useState<'AQI' | 'PM25'>( 'AQI' );
  const [ layer, setLayer ] = useState<'AQI' | 'PM25' | null>( 'AQI' );

  // Health Recommendations: which persona's advisory is shown under the Air panel. Defaults
  // to the Elderly persona (index 1) per the reference design. Pure UI state - no fetch.
  const [ healthPersona, setHealthPersona ] = useState( 1 );
  const [ healthExpanded, setHealthExpanded ] = useState( false );
  const [ pollutantTip, setPollutantTip ] = useState<{ code: string; top: number; left: number; side: 'left' | 'right' | 'top' | 'bottom' } | null>( null );
  // Hourly History: window offset for the prev/next chart navigation. 0 = latest week; a
  // positive value scrolls further back through the loaded airHistory points. Pure UI state.
  const [ historyOffset, setHistoryOffset ] = useState( 0 );
  const [ historyInspectIdx, setHistoryInspectIdx ] = useState<number | null>( null );

  const mapHost = useRef<HTMLDivElement | null>( null );
  const mapRef = useRef<unknown>( null );
  const atmosphereRef = useRef<HTMLDivElement | null>( null );
  const atmosphereFrameRef = useRef<number | null>( null );
  const initialGlobalViewRef = useRef( true );
  const markerRef = useRef<unknown>( null );
  const markerCtorRef = useRef<( new ( opts: Record<string, unknown> ) => unknown ) | null>( null );
  const placesLibRef = useRef<Record<string, unknown> | null>( null );
  const autocompleteTokenRef = useRef<unknown>( null );
  const geocoder = useRef<unknown>( null );
  // Cache the last fetched values per "lat,lng" so re-selecting a place bills nothing.
  const cache = useRef<Record<string, { ts: number; air: AirState | null; weather: WeatherState | null; pollen: PollenRow[] | null }>>( {} );
  const forecastCache = useRef<Record<string, {
    ts: number;
    hourly: WeatherHour[];
    daily: WeatherDay[];
    alerts: WeatherAlertRow[];
    airForecast: AirPoint[];
  }>>( {} );
  const historyCache = useRef<Record<string, { ts: number; points: AirPoint[] }>>( {} );
  const timeZoneCache = useRef<Record<string, LocationTimeState>>( {} );
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>( null );
  // The google.maps.ImageMapType instance for the continuous AQI heatmap tile overlay
  // (FEAT-001). Attached by DEFAULT once the KEYED map is initialized (layer defaults to
  // 'AQI'), pushed onto map.overlayMapTypes, and detached idempotently on toggle-off /
  // switch-to-PM2.5 / unmount. On the keyless path it is NEVER constructed.
  //
  // NOTE: both AQI and PM2.5 are now Google ImageMapType TILE overlays. The earlier deck.gl
  // GoogleMapsOverlay dot-grid (and its grid fetch/cache/abort refs) was superseded and has
  // been removed - deck.gl is no longer imported or used anywhere in this component.
  const heatmapOverlayRef = useRef<unknown>( null );

  useEffect( () => {
    const timer = window.setInterval( () => setClockNow( Date.now() ), 30_000 );
    return () => window.clearInterval( timer );
  }, [] );

  useEffect( () => {
    setHistoryInspectIdx( null );
  }, [ airHistory ] );

  useEffect( () => {
    setAirForecastInspectIdx( 0 );
  }, [ airForecast, airForecastHours ] );

  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) {
      setLocationTime( DEFAULT_LOCATION_TIME );
      return;
    }

    const cacheKey = `${place.lat.toFixed( 4 )},${place.lng.toFixed( 4 )}`;
    const cached = timeZoneCache.current[ cacheKey ];
    if ( cached ) {
      setLocationTime( cached );
      return;
    }

    // The card starts on IST by owner request. Once Google Time Zone resolves the selected
    // destination, swap to that location's real zone. Failed/restricted lookups remain
    // explicitly labelled as the IST default rather than inventing a local zone.
    setLocationTime( DEFAULT_LOCATION_TIME );
    const ac = new AbortController();
    const timestamp = Math.floor( Date.now() / 1000 );
    const params = new URLSearchParams( {
      location: `${place.lat},${place.lng}`,
      timestamp: String( timestamp ),
      key: MAPS_KEY,
    } );

    void fetch( `https://maps.googleapis.com/maps/api/timezone/json?${params.toString()}`, { signal: ac.signal } )
      .then( async res => res.ok ? res.json() : null )
      .then( data => {
        if ( ac.signal.aborted || data?.status !== 'OK' || typeof data?.timeZoneId !== 'string' ) return;
        const timeZoneName = typeof data.timeZoneName === 'string' ? data.timeZoneName : data.timeZoneId;
        const next: LocationTimeState = {
          timeZoneId: data.timeZoneId,
          timeZoneName,
          shortLabel: timeZoneShortLabel( data.timeZoneId, timeZoneName ),
          source: 'google',
        };
        timeZoneCache.current[ cacheKey ] = next;
        setLocationTime( next );
      } )
      .catch( () => { /* keep explicit IST default on Time Zone API failure */ } );

    return () => ac.abort();
  }, [ place.lat, place.lng, hasSelection ] );

  const openPollutantTip = useCallback( ( code: string, el: HTMLElement ) => {
    if ( typeof window === 'undefined' ) return;
    const rect = el.getBoundingClientRect();
    const gutter = 12;
    const gap = 12;
    const width = Math.min( 320, Math.max( 220, window.innerWidth - gutter * 2 ) );
    const estimatedHeight = Math.min( 208, Math.max( 120, window.innerHeight - gutter * 2 ) );
    const maxLeft = Math.max( gutter, window.innerWidth - width - gutter );
    const maxTop = Math.max( gutter, window.innerHeight - estimatedHeight - gutter );

    let left: number;
    let top: number;
    let side: 'left' | 'right' | 'top' | 'bottom';

    if ( window.innerWidth <= 700 ) {
      const below = rect.bottom + gap;
      const canOpenBelow = below + estimatedHeight <= window.innerHeight - gutter;
      side = canOpenBelow ? 'bottom' : 'top';
      left = clamp( rect.left + rect.width / 2 - width / 2, gutter, maxLeft );
      top = canOpenBelow
        ? clamp( below, gutter, maxTop )
        : clamp( rect.top - gap - estimatedHeight, gutter, maxTop );
    } else {
      const canOpenRight = rect.right + gap + width <= window.innerWidth - gutter;
      side = canOpenRight ? 'right' : 'left';
      left = canOpenRight
        ? clamp( rect.right + gap, gutter, maxLeft )
        : clamp( rect.left - width - gap, gutter, maxLeft );
      top = clamp( rect.top - 16, gutter, maxTop );
    }

    setPollutantTip( { code, top, left, side } );
  }, [] );

  useEffect( () => {
    if ( !pollutantTip || typeof document === 'undefined' ) return;

    const onPointerDown = ( event: PointerEvent ) => {
      const target = event.target;
      if ( !( target instanceof Element ) ) return;
      if ( target.closest( '.vl-live-air-pollutant-tip' ) || target.closest( '.vl-live-air-pollutant-info' ) ) return;
      setPollutantTip( null );
    };
    const onKeyDown = ( event: KeyboardEvent ) => {
      if ( event.key === 'Escape' ) setPollutantTip( null );
    };

    document.addEventListener( 'pointerdown', onPointerDown, true );
    document.addEventListener( 'keydown', onKeyDown );
    return () => {
      document.removeEventListener( 'pointerdown', onPointerDown, true );
      document.removeEventListener( 'keydown', onKeyDown );
    };
  }, [ pollutantTip ] );

  useEffect( () => {
    setMapCandidate( null );
    setAddressDescriptor( '' );
  }, [ place.lat, place.lng ] );

  useEffect( () => {
    if ( !MAPS_KEY || mapReady ) return;
    setMapFailed( false );
    const id = window.setTimeout( () => setMapFailed( true ), 12_000 );
    return () => window.clearTimeout( id );
  }, [ mapReady ] );

  /* ---------------------------------------------------------------------------------
     MAP. Fires on load WHEN a key is present. The Maps JS script is injected once per
     document with id 'gmaps-js' and reused across remounts, exactly as ContactLocation.
     Guarded by `if(!MAPS_KEY) return;` so no key means no script and no map. */
  useEffect( () => {
    if ( !MAPS_KEY || typeof window === 'undefined' ) return;
    const w = window as unknown as {
      google?: { maps?: Record<string, unknown> & {
        importLibrary?: ( name: string ) => Promise<Record<string, unknown>>;
      } };
    };

    let cancelled = false;

    // Wait up to ~5s for the canvas ref to attach. The effect can fire its init
    // before React has painted the conditionally-rendered map canvas, in which case
    // mapHost.current is still null; bailing then left a blank map with no error.
    const waitForHost = async (): Promise<HTMLDivElement | null> => {
      for ( let i = 0; i < 50; i++ ) {
        if ( cancelled ) return null;
        if ( mapHost.current ) return mapHost.current;
        await new Promise( r => setTimeout( r, 100 ) );
      }
      return mapHost.current;
    };

    // loading=async deliberately decouples Maps API readiness from the script
    // element's load event. Poll the namespace instead, so a newly injected loader,
    // an already-existing loader, and client-side route transitions all converge on
    // the same readiness path.
    const waitForMaps = async () => {
      for ( let i = 0; i < 50; i++ ) {
        if ( cancelled ) return null;
        const g = w.google?.maps;
        if ( g ) return g;
        await new Promise( r => setTimeout( r, 100 ) );
      }
      return w.google?.maps || null;
    };

    const init = async () => {
      const g = await waitForMaps();
      if ( cancelled || !g ) return;
      const host = await waitForHost();
      if ( cancelled || !host ) return;

      // WITH loading=async, the google.maps NAMESPACE exists on script load but its
      // constructors (Map, Marker, ...) are NOT populated until the relevant library
      // is imported. Calling `new google.maps.Map()` directly throws
      // "Map is not a constructor". The modern loader requires importLibrary().
      // We await the maps/marker/places libraries, then construct. Fall back to the
      // legacy namespace for any older loader that already populated it.
      type MapsCtors = {
        Map: new ( el: HTMLElement, opts: Record<string, unknown> ) => unknown;
        Marker: new ( opts: Record<string, unknown> ) => unknown;
        Geocoder: new () => unknown;
        places?: Record<string, unknown>;
      };
      // Import each library INDEPENDENTLY. A Promise.all here meant that if any one
      // import rejected (e.g. 'marker' under a loader that bundles it differently),
      // the whole block hit the catch and the map silently never built - exactly the
      // blank-canvas-no-error symptom. The map library is the only one that is
      // required; marker and places are best-effort and must not block the map.
      const imp = async ( name: string ): Promise<Record<string, unknown> | null> => {
        try {
          return typeof g.importLibrary === 'function' ? await g.importLibrary( name ) : null;
        } catch { return null; }
      };

      const legacy = g as unknown as MapsCtors;
      const mapsLib = await imp( 'maps' );
      if ( cancelled ) return;
      const MapCtor = ( mapsLib as { Map?: MapsCtors['Map'] } | null )?.Map || legacy.Map;
      if ( !MapCtor || !host ) return; // no map constructor -> degrade, no crash

      const markerLib = await imp( 'marker' );
      const placesLib = await imp( 'places' );
      // Geocoder belongs to the 'geocoding' library under the modern loader; it is NOT
      // on the raw namespace until importLibrary('geocoding') runs. Import it explicitly
      // so reverse-geocode-on-map-click and the search geocoding fallback get a real
      // Geocoder in a live browser, and only fall back to legacy.Geocoder for an older
      // loader that already populated the namespace. imp() swallows failures -> null.
      const geocodingLib = await imp( 'geocoding' );
      const maps: MapsCtors = {
        Map: MapCtor,
        Marker: ( markerLib as { Marker?: MapsCtors['Marker'] } | null )?.Marker || legacy.Marker,
        Geocoder: ( geocodingLib as { Geocoder?: MapsCtors['Geocoder'] } | null )?.Geocoder || legacy.Geocoder,
        places: ( placesLib as unknown as MapsCtors['places'] ) || legacy.places,
      };
      if ( cancelled ) return;

      const map = new maps.Map( host, {
        // Match the approved reference composition: India prominent, Himalaya/China above,
        // Arabian Sea + Bay of Bengal below. The map has worldwide data, but its camera is
        // destination-driven: only search/recent-place selection moves it.
        center: { lat: 25, lng: 86 },
        zoom: 4,
        mapTypeId: 'hybrid',
        // Owner interaction contract: no drag, pinch, trackpad pan, wheel zoom, double-click
        // zoom or keyboard movement. Programmatic fitBounds/setCenter from destination choice
        // still works, so selecting a place is the single camera-control path.
        gestureHandling: 'none',
        draggable: false,
        scrollwheel: false,
        disableDoubleClickZoom: true,
        disableDefaultUI: true,
        zoomControl: false,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: false,
        scaleControl: false,
        rotateControl: false,
        cameraControl: false,
        keyboardShortcuts: false,
        clickableIcons: false,
        styles: MAP_STYLES,
      } );
      mapRef.current = map;

      const motionMap = map as {
        addListener?: ( eventName: string, handler: () => void ) => { remove?: () => void };
        getCenter?: () => { lat?: () => number; lng?: () => number } | null;
        getZoom?: () => number | undefined;
      };
      const motionListeners: { remove?: () => void }[] = [];
      const syncAtmosphere = () => {
        if ( cancelled || atmosphereFrameRef.current !== null ) return;
        atmosphereFrameRef.current = requestAnimationFrame( () => {
          atmosphereFrameRef.current = null;
          const el = atmosphereRef.current;
          const center = motionMap.getCenter?.();
          const lat = center?.lat?.();
          const lng = center?.lng?.();
          const zoom = motionMap.getZoom?.();
          if ( !el || !Number.isFinite( lat ) || !Number.isFinite( lng ) || !Number.isFinite( zoom ) ) return;

          const anchor = worldPixel( 25, 86, zoom as number );
          const current = worldPixel( lat as number, lng as number, zoom as number );
          el.style.setProperty( '--vl-map-shift-x', `${clamp( anchor.x - current.x, -260, 260 ).toFixed( 1 )}px` );
          el.style.setProperty( '--vl-map-shift-y', `${clamp( anchor.y - current.y, -180, 180 ).toFixed( 1 )}px` );
          el.style.setProperty( '--vl-map-scale', clamp( Math.pow( 2, ( ( zoom as number ) - 4 ) * .06 ), .86, 1.18 ).toFixed( 3 ) );
        } );
      };

      if ( typeof motionMap.addListener === 'function' ) {
        for ( const eventName of [ 'center_changed', 'zoom_changed', 'idle' ] ) {
          motionListeners.push( motionMap.addListener( eventName, syncAtmosphere ) || {} );
        }
      }

      let resizeObserver: ResizeObserver | null = null;
      const onViewportResize = () => syncAtmosphere();
      if ( typeof ResizeObserver !== 'undefined' ) {
        resizeObserver = new ResizeObserver( onViewportResize );
        resizeObserver.observe( host );
      }
      window.visualViewport?.addEventListener( 'resize', onViewportResize );
      window.addEventListener( 'orientationchange', onViewportResize );
      syncAtmosphere();

      // No selected-place marker exists on load. Keep the constructor and create the
      // branded marker lazily after the first real selection.
      markerCtorRef.current = maps.Marker || null;

      if ( maps.Geocoder ) geocoder.current = new maps.Geocoder();
      placesLibRef.current = placesLib || maps.places || null;

      // Intentionally no map click handler. Location changes are owned by the search/recent
      // place selector only, which keeps the map, AQI tiles and atmosphere visually aligned.

      // A constructed Map is not the same thing as a painted map. With an invalid or
      // refused browser key Google can still create the map object while its tiles never
      // arrive, which previously hid the fallback and exposed a blank panel. Only reveal
      // the Maps JS canvas after the first visible tile batch has loaded.
      const mapWithEvents = map as {
        addListener?: ( eventName: string, handler: () => void ) => { remove?: () => void };
      };
      if ( typeof mapWithEvents.addListener === 'function' ) {
        let painted = false;
        motionListeners.push( mapWithEvents.addListener( 'tilesloaded', () => {
          if ( painted || cancelled ) return;
          painted = true;
          requestAnimationFrame( () => {
            if ( !cancelled ) setMapReady( true );
          } );
        } ) || {} );
      } else {
        requestAnimationFrame( () => {
          if ( !cancelled ) setMapReady( true );
        } );
      }

      ( host as HTMLDivElement & { __vlCleanup?: () => void } ).__vlCleanup = () => {
        motionListeners.forEach( listener => listener.remove?.() );
        resizeObserver?.disconnect();
        window.visualViewport?.removeEventListener( 'resize', onViewportResize );
        window.removeEventListener( 'orientationchange', onViewportResize );
        if ( atmosphereFrameRef.current !== null ) {
          cancelAnimationFrame( atmosphereFrameRef.current );
          atmosphereFrameRef.current = null;
        }
      };
    };

    // init is async (it awaits importLibrary); wrap so no unhandled promise floats.
    const runInit = () => { void init(); };

    // Do not use the script element's 'load' event as the readiness signal.
    // With Google's loading=async mode, API readiness is intentionally decoupled
    // from that event. runInit() waits for google.maps and then importLibrary().
    if ( w.google?.maps ) { runInit(); return () => {
      cancelled = true;
      ( mapHost.current as ( HTMLDivElement & { __vlCleanup?: () => void } ) | null )?.__vlCleanup?.();
    }; }

    const ID = 'gmaps-js';
    const existing = document.getElementById( ID );
    if ( existing ) {
      runInit();
      return () => {
      cancelled = true;
      ( mapHost.current as ( HTMLDivElement & { __vlCleanup?: () => void } ) | null )?.__vlCleanup?.();
    };
    }

    const script = document.createElement( 'script' );
    script.id = ID;
    script.async = true;
    // Places library requested so worldwide client-side autocomplete can run.
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent( MAPS_KEY )}&libraries=places&loading=async&v=beta`;
    document.head.appendChild( script );
    // Start the same namespace-readiness path immediately; it will resolve once
    // the async loader exposes google.maps, without depending on a DOM load event.
    runInit();
    return () => {
      cancelled = true;
      ( mapHost.current as ( HTMLDivElement & { __vlCleanup?: () => void } ) | null )?.__vlCleanup?.();
    };
  }, [] );

  /* ---------------------------------------------------------------------------------
     GOOGLE AIR HEATMAP TILES. AQI and PM2.5 both use Google's documented ImageMapType tile
     products. Only one tile overlay is attached at a time; the selected destination still owns
     current conditions, forecast and history data independently of the visual map layer. */
  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;

    const map = mapRef.current;

    // Detach the AQI heatmap ImageMapType from map.overlayMapTypes idempotently. overlayMapTypes
    // is an MVCArray; remove this exact instance by index so unrelated overlays are untouched,
    // and null the ref so a later toggle-on re-pushes exactly one (never a duplicate).
    const detachHeatmap = () => {
      const overlay = heatmapOverlayRef.current;
      if ( !overlay ) return;
      const omt = ( map as { overlayMapTypes?: {
        getLength?: () => number;
        getAt?: ( i: number ) => unknown;
        removeAt?: ( i: number ) => unknown;
        clear?: () => void;
      } } | null )?.overlayMapTypes;
      if ( omt ) {
        if ( typeof omt.getLength === 'function' && typeof omt.getAt === 'function' && typeof omt.removeAt === 'function' ) {
          for ( let i = omt.getLength() - 1; i >= 0; i-- ) {
            if ( omt.getAt( i ) === overlay ) omt.removeAt( i );
          }
        } else {
          // Test stub / minimal double exposes only clear(): the AQI heatmap is the only
          // overlayMapTypes entry this component ever pushes, so clearing it is clean.
          omt.clear?.();
        }
      }
      heatmapOverlayRef.current = null;
    };

    // No layer active -> ensure the heatmap overlay is detached and the single-point air clears.
    if ( !layer ) {
      detachHeatmap();
      requestAnimationFrame( () => { setDataLoading( false ); } );
      return;
    }
    if ( !map ) return;

    // AQI/PM2.5 -> continuous heatmap TILE overlay. Both are Google ImageMapType tile products;
    // attach the selected one exactly once. Attached by DEFAULT here (layer defaults to 'AQI')
    // once the keyed map is ready - never at module load, never on the keyless path.
    if ( layer === 'AQI' || layer === 'PM25' ) {
      detachHeatmap();
      const w = window as unknown as { google?: { maps?: {
        ImageMapType?: new ( opts: Record<string, unknown> ) => unknown;
        Size?: new ( w: number, h: number ) => unknown;
      } } };
      const gmaps = w.google?.maps;
      const omt = ( map as { overlayMapTypes?: { push?: ( v: unknown ) => void } } ).overlayMapTypes;
      const mapType = layer === 'AQI' ? AQI_HEATMAP_MAP_TYPE : PM25_HEATMAP_MAP_TYPE;
      if ( gmaps?.ImageMapType && gmaps?.Size && omt?.push && !heatmapOverlayRef.current ) {
        const imageMapType = new gmaps.ImageMapType( {
          name: layer === 'AQI' ? 'vl-live-aqi-heatmap' : 'vl-live-pm25-heatmap',
          tileSize: new gmaps.Size( 256, 256 ),
          minZoom: 0,
          maxZoom: 16,
          opacity: 0.64,
          getTileUrl: ( coord: { x: number; y: number }, zoom: number ): string =>
            `${AQI_HEATMAP_TILE_BASE}/${mapType}/heatmapTiles/${zoom}/${coord.x}/${coord.y}`
            + `?key=${encodeURIComponent( MAPS_KEY )}`,
        } );
        omt.push( imageMapType );
        heatmapOverlayRef.current = imageMapType;
      }
      requestAnimationFrame( () => { setDataLoading( false ); } );
      return () => { detachHeatmap(); };
    }

    return undefined;
  }, [ layer, place, refreshNonce, mapReady, hasSelection ] );

  /* ---------------------------------------------------------------------------------
     ATMOSPHERE VISUAL. No extra provider request is made here. The live Weather API payload
     already stored in `weather` drives SVG/CSS variables below; the visual itself stays
     screen-space so it remains smooth while Google handles pan/zoom underneath. */

  /* ---------------------------------------------------------------------------------
     LIVE DATA for the selected place. Air + Weather + Pollen fire together whenever
     the place changes AND a key is present. Each call is independently guarded,
     uses AbortController + Number.isFinite + silent degradation, and caches per place. */
  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;
    const { lat, lng } = place;
    const cacheKey = `${lat.toFixed( 4 )},${lng.toFixed( 4 )}`;

    const cached = cache.current[ cacheKey ];
    const CORE_TTL_MS = 5 * 60 * 1000;
    if ( cached && Date.now() - cached.ts < CORE_TTL_MS ) {
      requestAnimationFrame( () => {
        setAir( cached.air );
        setWeather( cached.weather );
        setPollen( cached.pollen );
        setCoreFetchedAt( cached.ts );
        setCoreError( false );
        setDataLoading( false );
      } );
      return;
    }

    setDataLoading( true );
    setCoreError( false );
    setAir( null );
    setWeather( null );
    setPollen( null );
    const ac = new AbortController();
    const store: { air: AirState | null; weather: WeatherState | null; pollen: PollenRow[] | null } = {
      air: null, weather: null, pollen: null,
    };

    // AIR QUALITY - India SKU currentConditions:lookup, India local AQI preferred.
    const fetchAir = async () => {
      try {
        const res = await fetch(
          `https://airquality.googleapis.com/v1/currentConditions:lookup?key=${encodeURIComponent( MAPS_KEY )}`,
          {
            method: 'POST',
            signal: ac.signal,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify( {
              location: { latitude: lat, longitude: lng },
              extraComputations: [
                'POLLUTANT_CONCENTRATION',
                'LOCAL_AQI',
                'HEALTH_RECOMMENDATIONS',
                'DOMINANT_POLLUTANT_CONCENTRATION',
                // Request Google's per-pollutant sources/effects strings so the info popover
                // on each pollutant row can show them. Scoped to this selected-place call only
                // (not the shared grid airRequestBody) to avoid bloating the many grid fetches.
                'POLLUTANT_ADDITIONAL_INFO',
              ],
              languageCode: 'en',
              universalAqi: true,
              ...localAqiOverride( place.regionCode ),
            } ),
          },
        );
        if ( !res.ok ) return;
        const data = await res.json();
        const parsedAir = airStateFromApiData( data );
        if ( parsedAir ) store.air = parsedAir;
      } catch { /* silent degradation */ }
    };

    // WEATHER - India SKU currentConditions:lookup (cheapest current snapshot).
    const fetchWeather = async () => {
      try {
        const res = await fetch(
          `https://weather.googleapis.com/v1/currentConditions:lookup?key=${encodeURIComponent( MAPS_KEY )}&location.latitude=${lat}&location.longitude=${lng}&unitsSystem=METRIC`,
          { signal: ac.signal },
        );
        if ( !res.ok ) return;
        const d = await res.json();
        const temp = d?.temperature?.degrees;
        const feels = d?.feelsLikeTemperature?.degrees;
        const humidity = d?.relativeHumidity;
        const windSpeed = d?.wind?.speed?.value;
        const windUnit = d?.wind?.speed?.unit;
        const windDeg = d?.wind?.direction?.degrees;
        const condition = d?.weatherCondition?.description?.text;
        const out: WeatherState = {};
        if ( Number.isFinite( temp ) ) out.temp = Math.round( temp );
        if ( Number.isFinite( feels ) ) out.feelsLike = Math.round( feels );
        if ( Number.isFinite( humidity ) ) out.humidity = Math.round( humidity );
        if ( Number.isFinite( windSpeed ) ) {
          out.windSpeed = Math.round( windSpeed );
          out.windUnit = windUnitLabel( typeof windUnit === 'string' ? windUnit : undefined );
        }
        if ( Number.isFinite( windDeg ) ) out.windDir = windDirection( windDeg );
        const gust = n( d?.wind?.gust?.value );
        const rainMm = n( d?.precipitation?.qpf?.quantity );
        const rainProb = n( d?.precipitation?.probability?.percent );
        const stormProb = n( d?.thunderstormProbability );
        const uv = n( d?.uvIndex );
        const visibility = n( d?.visibility?.distance );
        const pressure = n( d?.airPressure?.meanSeaLevelMillibars );
        const dew = n( d?.dewPoint?.degrees );
        const heat = n( d?.heatIndex?.degrees );
        const wet = n( d?.wetBulbTemperature?.degrees );
        const cloud = n( d?.cloudCover );
        if ( Number.isFinite( gust ) ) out.windGust = Math.round( gust );
        if ( Number.isFinite( rainMm ) ) out.rainMm = rainMm;
        if ( Number.isFinite( rainProb ) ) out.rainProb = Math.round( rainProb );
        if ( Number.isFinite( stormProb ) ) out.stormProb = Math.round( stormProb );
        if ( Number.isFinite( uv ) ) out.uv = Math.round( uv );
        if ( Number.isFinite( visibility ) ) out.visibilityKm = visibility;
        if ( Number.isFinite( pressure ) ) out.pressureHpa = Math.round( pressure );
        if ( Number.isFinite( dew ) ) out.dewPoint = Math.round( dew );
        if ( Number.isFinite( heat ) ) out.heatIndex = Math.round( heat );
        if ( Number.isFinite( wet ) ) out.wetBulb = Math.round( wet );
        if ( Number.isFinite( cloud ) ) out.cloudCover = Math.round( cloud );
        if ( typeof d?.currentTime === 'string' ) out.currentTime = d.currentTime;
        if ( typeof condition === 'string' ) out.condition = condition;
        // Only keep weather if at least one field arrived.
        if ( Object.keys( out ).length ) store.weather = out;
      } catch { /* silent degradation */ }
    };

    // Google Pollen has no India coverage. Keep the slot empty without issuing a request.
    const fetchPollen = async () => undefined;

    ( async () => {
      await Promise.all( [ fetchAir(), fetchWeather(), fetchPollen() ] );
      if ( ac.signal.aborted ) return;
      const fetchedAt = Date.now();
      cache.current[ cacheKey ] = { ts: fetchedAt, ...store };
      // First setState via rAF to avoid react-hooks/set-state-in-effect.
      requestAnimationFrame( () => {
        if ( ac.signal.aborted ) return;
        setAir( store.air );
        setWeather( store.weather );
        setPollen( store.pollen );
        setCoreFetchedAt( fetchedAt );
        setCoreError( !store.air && !store.weather );
        setDataLoading( false );
      } );
    } )();

    return () => ac.abort();
  }, [ place, refreshNonce, hasSelection ] );

  /* Extended forecast/history calls are separate from current conditions so a slow
     long-range endpoint never blocks the "Now" experience. */
  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;
    const ac = new AbortController();
    const { lat, lng } = place;
    const forecastKey = `${lat.toFixed( 4 )},${lng.toFixed( 4 )}`;
    const cachedForecast = forecastCache.current[ forecastKey ];
    const FORECAST_TTL_MS = 15 * 60 * 1000;
    if ( cachedForecast && Date.now() - cachedForecast.ts < FORECAST_TTL_MS ) {
      setWeatherHourly( cachedForecast.hourly );
      setWeatherDaily( cachedForecast.daily );
      setWeatherAlerts( cachedForecast.alerts );
      setAirForecast( cachedForecast.airForecast );
      return () => ac.abort();
    }

    setWeatherHourly( [] );
    setWeatherDaily( [] );
    setWeatherAlerts( [] );
    setAirForecast( [] );
    const forecastStore: {
      hourly: WeatherHour[];
      daily: WeatherDay[];
      alerts: WeatherAlertRow[];
      airForecast: AirPoint[];
    } = { hourly: [], daily: [], alerts: [], airForecast: [] };

    const getJson = async ( url: string ) => {
      const res = await fetch( url, { signal: ac.signal } );
      if ( !res.ok ) return null;
      return res.json();
    };

    const loadHourly = async () => {
      const rows: WeatherHour[] = [];
      let pageToken = '';
      for ( let page = 0; page < 2 && !ac.signal.aborted; page++ ) {
        let url = 'https://weather.googleapis.com/v1/forecast/hours:lookup?key=' + encodeURIComponent( MAPS_KEY )
          + '&location.latitude=' + lat + '&location.longitude=' + lng
          + '&hours=48&pageSize=24&unitsSystem=METRIC&languageCode=en';
        if ( pageToken ) url += '&pageToken=' + encodeURIComponent( pageToken );
        const data = await getJson( url );
        if ( !data || ac.signal.aborted ) break;
        rows.push( ...( Array.isArray( data.forecastHours ) ? data.forecastHours : [] )
          .map( ( row: Record<string, any> ) => weatherHourFromApi( row ) )
          .filter( Boolean ) as WeatherHour[] );
        pageToken = typeof data.nextPageToken === 'string' ? data.nextPageToken : '';
        if ( !pageToken ) break;
      }
      forecastStore.hourly = rows.slice( 0, 48 );
      setWeatherHourly( rows.slice( 0, 48 ) );
    };

    const loadDaily = async () => {
      const url = 'https://weather.googleapis.com/v1/forecast/days:lookup?key=' + encodeURIComponent( MAPS_KEY )
        + '&location.latitude=' + lat + '&location.longitude=' + lng
        + '&days=10&unitsSystem=METRIC&languageCode=en';
      const data = await getJson( url );
      if ( !data || ac.signal.aborted ) return;
      const rows: WeatherDay[] = ( Array.isArray( data.forecastDays ) ? data.forecastDays : [] ).map( ( row: any, i: number ) => {
        const d = row?.displayDate || {};
        const date = d?.year && d?.month && d?.day ? new Date( Date.UTC( d.year, d.month - 1, d.day ) ) : new Date();
        const p = row?.daytimeForecast || row?.nighttimeForecast || {};
        const min = n( row?.minTemperature?.degrees );
        const max = n( row?.maxTemperature?.degrees );
        const rain = n( p?.precipitation?.probability?.percent );
        return {
          time: date.getTime(),
          label: i === 0 ? 'Today' : new Intl.DateTimeFormat( 'en-IN', { weekday: 'short', timeZone: 'UTC' } ).format( date ),
          dateLabel: new Intl.DateTimeFormat( 'en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' } ).format( date ),
          ...( Number.isFinite( min ) ? { min: Math.round( min ) } : {} ),
          ...( Number.isFinite( max ) ? { max: Math.round( max ) } : {} ),
          ...( Number.isFinite( rain ) ? { rainProb: Math.round( rain ) } : {} ),
          ...( typeof p?.weatherCondition?.description?.text === 'string' ? { condition: p.weatherCondition.description.text } : {} ),
          ...( typeof p?.weatherCondition?.iconBaseUri === 'string' ? { icon: p.weatherCondition.iconBaseUri } : {} ),
          ...( typeof row?.sunEvents?.sunriseTime === 'string' ? { sunrise: row.sunEvents.sunriseTime } : {} ),
          ...( typeof row?.sunEvents?.sunsetTime === 'string' ? { sunset: row.sunEvents.sunsetTime } : {} ),
        };
      } );
      forecastStore.daily = rows;
      setWeatherDaily( rows );
    };

    // Google Weather public alerts are not supported for India.
    const loadAlerts = async () => undefined;

    const loadAirForecast = async () => {
      const start = new Date();
      start.setUTCMinutes( 0, 0, 0 );
      start.setUTCHours( start.getUTCHours() + 1 );
      const end = new Date( start.getTime() + 96 * 60 * 60 * 1000 );
      const res = await fetch(
        'https://airquality.googleapis.com/v1/forecast:lookup?key=' + encodeURIComponent( MAPS_KEY ),
        {
          method: 'POST',
          signal: ac.signal,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( {
            location: { latitude: lat, longitude: lng },
            period: { startTime: start.toISOString(), endTime: end.toISOString() },
            pageSize: 96,
            universalAqi: true,
            ...localAqiOverride( place.regionCode ),
            extraComputations: [
              'LOCAL_AQI',
              'POLLUTANT_CONCENTRATION',
              'DOMINANT_POLLUTANT_CONCENTRATION',
              'HEALTH_RECOMMENDATIONS',
              'POLLUTANT_ADDITIONAL_INFO',
            ],
            languageCode: 'en',
          } ),
        },
      );
      if ( !res.ok || ac.signal.aborted ) return;
      const data = await res.json();
      const rows = ( Array.isArray( data.hourlyForecasts ) ? data.hourlyForecasts : [] )
        .map( ( row: Record<string, any> ) => airPointFromApi( row ) )
        .filter( Boolean ) as AirPoint[];
      forecastStore.airForecast = rows;
      setAirForecast( rows );
    };

    void Promise.allSettled( [ loadHourly(), loadDaily(), loadAlerts(), loadAirForecast() ] ).then( () => {
      if ( ac.signal.aborted ) return;
      forecastCache.current[ forecastKey ] = { ts: Date.now(), ...forecastStore };
    } );
    return () => ac.abort();
  }, [ place, hasSelection ] );

  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;
    const ac = new AbortController();
    setWeatherHistory( [] );
    const { lat, lng } = place;
    const run = async () => {
      try {
        const url = 'https://weather.googleapis.com/v1/history/hours:lookup?key=' + encodeURIComponent( MAPS_KEY )
          + '&location.latitude=' + lat + '&location.longitude=' + lng
          + '&hours=24&pageSize=24&unitsSystem=METRIC&languageCode=en';
        const res = await fetch( url, { signal: ac.signal } );
        if ( !res.ok || ac.signal.aborted ) return;
        const data = await res.json();
        const rows = ( Array.isArray( data.historyHours ) ? data.historyHours : [] )
          .map( ( row: Record<string, any> ) => weatherHourFromApi( row ) )
          .filter( Boolean ) as WeatherHour[];
        rows.sort( ( a, b ) => a.time - b.time );
        if ( !ac.signal.aborted ) setWeatherHistory( rows.slice( -24 ) );
      } catch { /* historical weather is optional */ }
    };
    void run();
    return () => ac.abort();
  }, [ place, hasSelection ] );

  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;
    const ac = new AbortController();
    const { lat, lng } = place;
    // Reset paging whenever the place/range changes so the pinned "current" bubble
    // tracks the newest point of the new series instead of a stale offset.
    setHistoryOffset( 0 );
    const historyKey = `${lat.toFixed( 4 )},${lng.toFixed( 4 )}:${historyRange}`;
    const cachedHistory = historyCache.current[ historyKey ];
    const HISTORY_TTL_MS = historyRange === 24 ? 15 * 60 * 1000 : 60 * 60 * 1000;
    if ( cachedHistory && Date.now() - cachedHistory.ts < HISTORY_TTL_MS ) {
      setAirHistory( cachedHistory.points );
      setHistoryLoading( false );
      return () => ac.abort();
    }
    setHistoryLoading( true );
    setAirHistory( [] );

    const run = async () => {
      const points: AirPoint[] = [];
      let pageToken = '';
      let page = 0;
      do {
        const body: Record<string, unknown> = {
          location: { latitude: lat, longitude: lng },
          hours: historyRange,
          pageSize: Math.min( 100, historyRange ),
          universalAqi: true,
          ...localAqiOverride( place.regionCode ),
          extraComputations: [ 'LOCAL_AQI', 'POLLUTANT_CONCENTRATION', 'DOMINANT_POLLUTANT_CONCENTRATION' ],
          languageCode: 'en',
        };
        if ( pageToken ) body.pageToken = pageToken;
        const res = await fetch(
          'https://airquality.googleapis.com/v1/history:lookup?key=' + encodeURIComponent( MAPS_KEY ),
          {
            method: 'POST',
            signal: ac.signal,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify( body ),
          },
        );
        if ( !res.ok ) break;
        const data = await res.json();
        ( Array.isArray( data.hoursInfo ) ? data.hoursInfo : [] ).forEach( ( row: Record<string, any> ) => {
          const p = airPointFromApi( row );
          if ( p ) points.push( p );
        } );
        pageToken = typeof data.nextPageToken === 'string' ? data.nextPageToken : '';
        page += 1;
      } while ( pageToken && page < 8 && !ac.signal.aborted );
      if ( !ac.signal.aborted ) {
        points.sort( ( a, b ) => a.time - b.time );
        historyCache.current[ historyKey ] = { ts: Date.now(), points };
        setAirHistory( points );
        setHistoryLoading( false );
      }
    };
    void run().catch( () => { if ( !ac.signal.aborted ) setHistoryLoading( false ); } );
    return () => ac.abort();
  }, [ place, historyRange, hasSelection ] );

  /* ---------------------------------------------------------------------------------
     RECENTRE the map + move the marker when the place changes (after the map exists). */
  useEffect( () => {
    const w = window as unknown as { google?: { maps?: unknown } };
    const map = mapRef.current as {
      setCenter?: ( p: { lat: number; lng: number } ) => void;
      setZoom?: ( zoom: number ) => void;
      fitBounds?: ( bounds: { north: number; south: number; east: number; west: number }, padding?: number ) => void;
    } | null;
    if ( !map || !w.google?.maps || !hasSelection ) return;

    if ( !markerRef.current && markerCtorRef.current ) {
      const MarkerCtor = markerCtorRef.current;
      // Normal Material location marker, created lazily after the first valid selection.
      markerRef.current = new MarkerCtor( {
        position: { lat: place.lat, lng: place.lng },
        map,
        title: place.name,
        icon: LOCATION_MARKER_ICON,
      } );
    }
    const marker = markerRef.current as {
      setPosition?: ( p: { lat: number; lng: number } ) => void;
      setTitle?: ( t: string ) => void;
      setMap?: ( m: unknown ) => void;
    } | null;
    if ( initialGlobalViewRef.current ) {
      initialGlobalViewRef.current = false;
    } else if ( place.viewport && map.fitBounds ) map.fitBounds( place.viewport, 56 );
    else {
      map.setCenter?.( { lat: place.lat, lng: place.lng } );
      map.setZoom?.( 14 );
    }
    marker?.setMap?.( map );
    marker?.setPosition?.( { lat: place.lat, lng: place.lng } );
    marker?.setTitle?.( place.name );
  }, [ place, mapReady, hasSelection ] );

  /* ---------------------------------------------------------------------------------
     SEARCH - modern Places Autocomplete Data API with one session token per query/
     selection session. This avoids legacy Text Search on every keystroke and is
     intentionally worldwide. Geocoding remains only as an unavailable-Places fallback. */
  const ensurePlacesLibrary = useCallback( async (): Promise<Record<string, unknown> | null> => {
    if ( placesLibRef.current ) return placesLibRef.current;
    const w = window as unknown as { google?: { maps?: { importLibrary?: ( name: string ) => Promise<Record<string, unknown>>; places?: Record<string, unknown> } } };
    try {
      const lib = w.google?.maps?.importLibrary
        ? await w.google.maps.importLibrary( 'places' )
        : w.google?.maps?.places || null;
      placesLibRef.current = lib || null;
      return placesLibRef.current;
    } catch {
      return null;
    }
  }, [] );

  // Obtain a Geocoder the same way the map init effect does: via importLibrary('geocoding')
  // under the modern loader, falling back to a pre-populated namespace Geocoder only for an
  // older loader. Mirrors ensurePlacesLibrary so the search geocoding fallback never depends
  // on legacy.Geocoder being seeded on google.maps. Caches into geocoder.current.
  const ensureGeocoder = useCallback( async (): Promise<{
    geocode?: ( req: Record<string, unknown>, cb: ( rows: unknown[] | null, status: string ) => void ) => void;
  } | null> => {
    const existing = geocoder.current as {
      geocode?: ( req: Record<string, unknown>, cb: ( rows: unknown[] | null, status: string ) => void ) => void;
    } | null;
    if ( existing ) return existing;
    const w = window as unknown as { google?: { maps?: {
      importLibrary?: ( name: string ) => Promise<Record<string, unknown>>;
      Geocoder?: new () => unknown;
    } } };
    try {
      const lib = w.google?.maps?.importLibrary
        ? await w.google.maps.importLibrary( 'geocoding' )
        : null;
      const Ctor = ( lib as { Geocoder?: new () => unknown } | null )?.Geocoder
        || w.google?.maps?.Geocoder;
      if ( Ctor ) geocoder.current = new Ctor();
    } catch { /* no geocoder available -> degrade */ }
    return geocoder.current as {
      geocode?: ( req: Record<string, unknown>, cb: ( rows: unknown[] | null, status: string ) => void ) => void;
    } | null;
  }, [] );

  /* ---------------------------------------------------------------------------------
     Place enrichment: the on-map selected label shows a human address descriptor
     (landmark/area) when the Geocoder exposes one. Optional and degrades cleanly when
     a project has not enabled the service. */
  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || !mapReady || typeof window === 'undefined' ) return;
    let cancelled = false;

    const describe = async () => {
      const gc = await ensureGeocoder();
      if ( !gc?.geocode || cancelled ) return;
      const request: Record<string, unknown> = place.placeId
        ? { placeId: place.placeId, extraComputations: [ 'ADDRESS_DESCRIPTORS' ] }
        : { location: { lat: place.lat, lng: place.lng }, extraComputations: [ 'ADDRESS_DESCRIPTORS' ] };
      try {
        gc.geocode( request, ( rows, status ) => {
          if ( cancelled || status !== 'OK' || !Array.isArray( rows ) || !rows.length ) return;
          const descriptor = ( rows[ 0 ] as any )?.address_descriptor;
          const landmark = Array.isArray( descriptor?.landmarks ) ? descriptor.landmarks[ 0 ] : null;
          const area = Array.isArray( descriptor?.areas ) ? descriptor.areas[ 0 ] : null;
          const landmarkName = landmark?.display_name || landmark?.displayName?.text || landmark?.display_name?.text;
          const areaName = area?.display_name || area?.displayName?.text || area?.display_name?.text;
          const relationship = String( landmark?.spatial_relationship || '' );
          const relationshipLabel: Record<string, string> = {
            NEAR: 'Near', WITHIN: 'Within', BESIDE: 'Beside', ACROSS_THE_ROAD: 'Across the road from',
            DOWN_THE_ROAD: 'Down the road from', AROUND_THE_CORNER: 'Around the corner from', BEHIND: 'Behind',
          };
          const parts: string[] = [];
          if ( landmarkName ) parts.push( `${relationshipLabel[ relationship ] || 'Near'} ${landmarkName}` );
          if ( areaName && areaName !== landmarkName ) parts.push( `Within ${areaName}` );
          if ( parts.length ) setAddressDescriptor( parts.join( ' · ' ) );
        } );
      } catch { /* descriptor enrichment is optional */ }
    };

    void describe();
    return () => {
      cancelled = true;
      ( mapHost.current as ( HTMLDivElement & { __vlCleanup?: () => void } ) | null )?.__vlCleanup?.();
    };
  }, [ place.lat, place.lng, place.placeId, hasSelection, mapReady, ensureGeocoder ] );

  const runSearch = useCallback( async ( text: string ) => {
    if ( !MAPS_KEY || !text.trim() ) {
      setResults( [] );
      setOpen( false );
      setSearchStatus( 'idle' );
      return;
    }
    setSearchStatus( 'searching' );
    const lib = await ensurePlacesLibrary();
    const Auto = lib?.AutocompleteSuggestion as {
      fetchAutocompleteSuggestions?: ( req: Record<string, unknown> ) => Promise<{ suggestions?: unknown[] }>;
    } | undefined;
    const Token = lib?.AutocompleteSessionToken as ( new () => unknown ) | undefined;

    if ( Auto?.fetchAutocompleteSuggestions && Token ) {
      try {
        if ( !autocompleteTokenRef.current ) autocompleteTokenRef.current = new Token();
        const out = await Auto.fetchAutocompleteSuggestions( {
          input: text,
          sessionToken: autocompleteTokenRef.current,
        } );
        const mapped: SearchResult[] = ( Array.isArray( out?.suggestions ) ? out.suggestions : [] )
          .map( suggestion => {
            const prediction = ( suggestion as { placePrediction?: any } )?.placePrediction;
            if ( !prediction ) return null;
            const name = prediction.mainText?.text
              || prediction.mainText?.toString?.()
              || prediction.text?.toString?.()
              || 'Place';
            const addr = prediction.secondaryText?.text
              || prediction.secondaryText?.toString?.()
              || '';
            return { name: String( name ), addr: String( addr ), prediction };
          } )
          .filter( Boolean )
          .slice( 0, 6 ) as SearchResult[];
        if ( mapped.length ) {
          setResults( mapped );
          setActive( 0 );
          setOpen( true );
          setSearchStatus( 'idle' );
          return;
        }
        // A permitted Maps JS load can still have Places (New) blocked by the browser key's
        // API-target restrictions. Empty suggestions must not dead-end the field: fall through
        // to the Geocoder path below so destination search remains usable.
        autocompleteTokenRef.current = null;
      } catch {
        autocompleteTokenRef.current = null;
      }
    }

    // Fallback for a partial/restricted Places load: Geocoding is worldwide. The Geocoder
    // comes from importLibrary('geocoding') via ensureGeocoder, NOT from a pre-populated
    // google.maps.Geocoder, so this path works under the modern loading=async loader.
    const gc = await ensureGeocoder();
    if ( !gc?.geocode ) {
      setResults( [] );
      setOpen( true );
      setSearchStatus( 'unavailable' );
      return;
    }
    gc.geocode(
      { address: text },
      ( rows, status ) => {
        // ZERO_RESULTS is a benign "nothing matched"; every other non-OK status
        // (REQUEST_DENIED / OVER_QUERY_LIMIT / INVALID_REQUEST / UNKNOWN_ERROR, etc.)
        // is a real failure the user must see via the existing 'unavailable' retry
        // affordance rather than being silently swallowed.
        if ( status !== 'OK' || !Array.isArray( rows ) ) {
          setResults( [] );
          setOpen( true );
          setSearchStatus( status === 'ZERO_RESULTS' ? 'no-results' : 'unavailable' );
          return;
        }
        const mapped: SearchResult[] = rows
          .slice( 0, 6 )
          .map( ( row: unknown ): SearchResult | null => {
            const pr = row as { formatted_address?: string; geometry?: { location?: { lat: () => number; lng: () => number } } };
            const loc = pr.geometry?.location;
            const lat = loc?.lat?.();
            const lng = loc?.lng?.();
            if ( !Number.isFinite( lat ) || !Number.isFinite( lng ) ) return null;
            const country = ( row as { address_components?: { types?: string[]; short_name?: string }[] } ).address_components
              ?.find( component => component.types?.includes( 'country' ) )?.short_name;
            const place: PlaceState = {
              name: pr.formatted_address?.split( ',' )[ 0 ] || 'Place',
              addr: pr.formatted_address || '',
              lat: lat as number,
              lng: lng as number,
              ...( typeof country === 'string' && country ? { regionCode: country.toUpperCase() } : {} ),
            };
            return { name: place.name, addr: place.addr, place };
          } )
          // The predicate narrows to the shape the `.map` above ACTUALLY produces, not to
          // `SearchResult`. `SearchResult.place` is optional, so `row is SearchResult` is not
          // assignable to this parameter's `{ ..., place: PlaceState } | null` and TS rejects the
          // guard outright (TS2677) - which then leaves `mapped` as `(... | null)[]` and fails
          // the annotation too (TS2322). Narrowing to the concrete shape satisfies both, and the
          // result is still assignable to `SearchResult[]` because a required `place` meets an
          // optional one. Behaviour is unchanged: every element here is an object or null.
          .filter( ( row ): row is { name: string; addr: string; place: PlaceState } => row !== null );
        setResults( mapped );
        setActive( mapped.length ? 0 : -1 );
        setOpen( true );
        setSearchStatus( mapped.length ? 'idle' : 'no-results' );
      },
    );
  }, [ ensurePlacesLibrary, ensureGeocoder ] );

  const onQueryChange = ( e: React.ChangeEvent<HTMLInputElement> ) => {
    const v = e.target.value;
    setQuery( v );
    if ( searchTimer.current ) clearTimeout( searchTimer.current );
    if ( !v.trim() ) {
      autocompleteTokenRef.current = null;
      const recent = recentPlaces().map( place => ( { name: place.name, addr: place.addr, place } ) );
      setResults( recent );
      setActive( recent.length ? 0 : -1 );
      setOpen( recent.length > 0 );
      setSearchStatus( 'idle' );
      return;
    }
    // SEARCH_DEBOUNCE_MS (120ms) keeps one request per settled keystroke while feeling instant.
    searchTimer.current = setTimeout( () => { void runSearch( v ); }, SEARCH_DEBOUNCE_MS );
  };

  const choose = useCallback( async ( r: SearchResult ) => {
    let next = r.place;
    if ( !next && r.prediction?.toPlace ) {
      try {
        const googlePlace = r.prediction.toPlace();
        await googlePlace.fetchFields?.( { fields: [ 'id', 'displayName', 'formattedAddress', 'location', 'addressComponents', ...PLACE_META_FIELDS ] } );
        const lat = googlePlace.location?.lat?.();
        const lng = googlePlace.location?.lng?.();
        if ( Number.isFinite( lat ) && Number.isFinite( lng ) ) {
          next = {
            name: googlePlace.displayName || r.name,
            addr: googlePlace.formattedAddress || r.addr,
            lat: lat as number,
            lng: lng as number,
            placeId: googlePlace.id,
            // Surface only the metadata Google actually returned; absent fields stay
            // undefined so the on-map label renders no placeholder for them.
            ...metaFromGooglePlace( googlePlace ),
          };
        }
      } catch {
        setSearchStatus( 'unavailable' );
      } finally {
        // Place.fetchFields concludes the billing session; never reuse its token.
        autocompleteTokenRef.current = null;
      }
    }
    if ( !next ) return;
    rememberPlace( next );
    setPlace( next );
    setHasSelection( true );
    // A fresh search selection owns the view. Clear transient preview metadata so the
    // on-map label and camera follow only the newly chosen location.
    setMapCandidate( null );
    setQuery( next.name );
    setOpen( false );
    setResults( [] );
    setActive( -1 );
    setSearchStatus( 'idle' );
  }, [] );

  const onKeyDown = ( e: React.KeyboardEvent<HTMLInputElement> ) => {
    if ( e.key === 'Escape' ) {
      setOpen( false );
      setSearchStatus( 'idle' );
      return;
    }
    if ( !open || !results.length ) return;
    if ( e.key === 'ArrowDown' ) { e.preventDefault(); setActive( i => Math.min( i + 1, results.length - 1 ) ); }
    else if ( e.key === 'ArrowUp' ) { e.preventDefault(); setActive( i => Math.max( i - 1, 0 ) ); }
    else if ( e.key === 'Enter' ) { e.preventDefault(); if ( active >= 0 ) void choose( results[ active ] ); }
  };

  useEffect( () => () => { if ( searchTimer.current ) clearTimeout( searchTimer.current ); }, [] );

  // The floating Air card and the on-map label read these. The former LEFT-panel
  // derivations (photo rail, 24h forecast rail, best-outside / rain signals, 4-day
  // outlook, weather-context) were removed with the panel they fed; the underlying
  // weather/air history + forecast state is still fetched and kept intact for the
  // Weather phase and the map layers.
  const previewPlace = mapCandidate || place;
  const currentPm25 = air?.pollutants.find( p => p.code === 'pm25' ) || null;
  const activePollutant = pollutantTip
    ? air?.pollutants.find( p => p.code === pollutantTip.code ) || null
    : null;
  const mapActive = Boolean( MAPS_KEY );

  const liveHealthPersonas = useMemo( () => {
    const recommendations = air?.healthRecommendations;
    if ( !recommendations ) return [];
    return HEALTH_PERSONAS
      .map( persona => ( {
        ...persona,
        recommendation: recommendations[ persona.apiKey ],
      } ) )
      .filter( ( persona ): persona is HealthPersonaDefinition & { recommendation: string } =>
        typeof persona.recommendation === 'string' && Boolean( persona.recommendation.trim() )
      );
  }, [ air?.healthRecommendations ] );

  useEffect( () => {
    if ( !liveHealthPersonas.length ) {
      if ( healthPersona !== 0 ) setHealthPersona( 0 );
      return;
    }
    if ( healthPersona >= liveHealthPersonas.length ) setHealthPersona( Math.min( 1, liveHealthPersonas.length - 1 ) );
  }, [ healthPersona, liveHealthPersonas.length ] );

  const activeHealthPersona = liveHealthPersonas[ healthPersona ] || liveHealthPersonas[ 0 ] || null;
  const healthNeedsMore = Boolean( activeHealthPersona && activeHealthPersona.recommendation.length > 180 );
  const locationClock = formatLocationClock( clockNow, locationTime.timeZoneId );
  const locationZoneLabel = locationTime.source === 'google'
    ? locationTime.shortLabel
    : 'IST default';

  const atmosphereStyle = useMemo( () => {
    const cloud = Number.isFinite( weather?.cloudCover ) ? weather?.cloudCover as number : 58;
    const rain = Number.isFinite( weather?.rainProb ) ? weather?.rainProb as number : 24;
    const storm = Number.isFinite( weather?.stormProb ) ? weather?.stormProb as number : 18;
    const wind = Number.isFinite( weather?.windSpeed ) ? weather?.windSpeed as number : 16;
    const cloudOpacity = Math.min( .72, Math.max( .28, .24 + cloud / 100 * .52 ) );
    const stormOpacity = Math.min( .72, Math.max( .12, ( rain + storm ) / 180 ) );
    const windOpacity = Math.min( .62, Math.max( .26, .24 + wind / 120 ) );
    const windDuration = Math.max( 5.5, 17 - Math.min( 50, wind ) * .18 );
    const cloudDuration = Math.max( 16, windDuration * 3.2 );
    const vortexDuration = Math.max( 11, windDuration * 2.1 );
    return {
      '--vl-cloud-opacity': cloudOpacity.toFixed( 3 ),
      '--vl-storm-opacity': stormOpacity.toFixed( 3 ),
      '--vl-wind-opacity': windOpacity.toFixed( 3 ),
      '--vl-wind-angle': `${windDirectionDegrees( weather?.windDir )}deg`,
      '--vl-wind-duration': `${windDuration.toFixed( 1 )}s`,
      '--vl-cloud-duration': `${cloudDuration.toFixed( 1 )}s`,
      '--vl-vortex-duration': `${vortexDuration.toFixed( 1 )}s`,
    } as React.CSSProperties;
  }, [ weather ] );

  return (
    <section className="vl-live" aria-label="VayuLok conditions">
      { mapReady && (
        <div className="vl-live-map-search">
          <label className="vl-live-sr-only" htmlFor="vl-live-search">Search a city or place</label>
          <div className="vl-live-search">
            <div className="vl-live-search-field">
              <input
                id="vl-live-search"
                type="search"
                role="combobox"
                aria-controls="vl-live-search-results"
                aria-expanded={ open }
                aria-autocomplete="list"
                autoComplete="off"
                autoCorrect="off"
                spellCheck={ false }
                placeholder="Search"
                value={ query }
                onChange={ onQueryChange }
                onFocus={ () => {
                  if ( query.trim() ) {
                    if ( results.length ) setOpen( true );
                    else void runSearch( query );
                    return;
                  }
                  const recent = recentPlaces().map( place => ( { name: place.name, addr: place.addr, place } ) );
                  setResults( recent ); setActive( recent.length ? 0 : -1 ); setOpen( recent.length > 0 ); setSearchStatus( 'idle' );
                } }
                onKeyDown={ onKeyDown }
              />
            </div>
            <ul className="vl-live-search-results" id="vl-live-search-results" role="listbox" aria-label="Matching places" hidden={ !open || !results.length }>
              { results.map( ( r, i ) => (
                <li key={ `${r.name}-${r.addr}-${i}` } role="option" aria-selected={ i === active } onPointerDown={ e => { e.preventDefault(); void choose( r ); } }>
                  <strong>{ r.name }</strong>{ r.addr && <span>{ r.addr }</span> }
                </li>
              ) ) }
            </ul>
            { searchStatus === 'searching' && <p className="vl-live-search-status" role="status">Searching worldwide…</p> }
            { searchStatus === 'no-results' && <p className="vl-live-search-status" role="status">Place not found.</p> }
            { searchStatus === 'unavailable' && <p className="vl-live-search-status" role="status">Place search is temporarily unavailable.</p> }
          </div>
        </div>
      ) }

      <main className="vl-live-shell">


        <div className="vl-live-workspace">
          <section className="vl-live-map-region" aria-label="Map">
            <div className="vl-live-map-shell">

              {/* FLOATING AIR QUALITY CARD. Overlays the map in the top-left corner, inset so
                  it never reaches Google's bottom-left logo or bottom-right legal notices. The
                  markup stays INLINE here (styled-jsx scopes only statically-visible elements),
                  every class is vl-live- prefixed, and it renders live Air content only when
                  `air` is present - on the keyless path (air === null) only the static shell
                  (header + toggle + honest empty state) shows, firing no fetch of its own. */}
              <div className="vl-live-air-card-wrap">
              <aside className="vl-live-air-card" aria-label="Air quality details" onScroll={ () => setPollutantTip( null ) }>
                <div className="vl-live-air-context" aria-label="Selected location and local time">
                  <span className="vl-live-air-context-item is-location" title={ place.addr || place.name }>
                    <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.location } /></svg>
                    <strong>{ place.name }</strong>
                  </span>
                  <span
                    className="vl-live-air-context-item is-time"
                    title={ locationTime.source === 'google'
                      ? `${locationTime.timeZoneName} from Google Time Zone API`
                      : 'India Standard Time default while Google Time Zone is unavailable or loading' }
                  >
                    <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.schedule } /></svg>
                    <time dateTime={ new Date( clockNow ).toISOString() }>{ locationClock }</time>
                    <small>{ locationZoneLabel }</small>
                  </span>
                </div>

                {/* Air/Weather toggle - the same tint + saturated dot idiom as the hero's
                    rotating pill (Air #e0f7c8/#3da35a, Weather #dbeafe/#2563eb). Drives the
                    existing detailTab state; clicking it triggers no network call. */}
                <div className="vl-live-air-toggle" role="tablist" aria-label="Air or weather details">
                  <button
                    type="button"
                    role="tab"
                    id="vl-live-air-tab"
                    aria-controls="vl-live-air-panel"
                    aria-selected={ detailTab === 'air' }
                    className={ `vl-live-air-toggle-btn is-air ${detailTab === 'air' ? 'is-active' : ''}`.trim() }
                    onClick={ () => setDetailTab( 'air' ) }
                  >
                    <i className="vl-live-air-toggle-dot" aria-hidden="true" />Air
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="vl-live-weather-tab"
                    aria-controls="vl-live-weather-panel"
                    aria-selected={ detailTab === 'weather' }
                    className={ `vl-live-air-toggle-btn is-weather ${detailTab === 'weather' ? 'is-active' : ''}`.trim() }
                    onClick={ () => setDetailTab( 'weather' ) }
                  >
                    <i className="vl-live-air-toggle-dot" aria-hidden="true" />Weather
                  </button>
                </div>

                { detailTab === 'air' && (
                  air ? (
                    <div className="vl-live-air-panel" role="tabpanel" id="vl-live-air-panel" aria-labelledby="vl-live-air-tab" aria-label="Air details">
                      <div className="vl-live-air-gauge-row">
                        <span className="vl-live-air-aqi-spine" aria-hidden="true" />
                        <div
                          className="vl-live-air-aqi-score"
                          role="img"
                          aria-label={ `${air.indexName || 'Air quality index'} ${air.aqiDisplay || Math.round( air.aqi )}, ${air.word}` }
                        >
                          <strong className="vl-live-air-aqi-number" aria-hidden="true">{ air.aqiDisplay || Math.round( air.aqi ) }</strong>
                          <span className="vl-live-air-aqi-unit" aria-hidden="true">AQI</span>
                        </div>
                        <div className="vl-live-air-gauge-meta">
                          <strong className="vl-live-air-gauge-word">{ air.word } air quality</strong>
                          <div className="vl-live-air-summary-meta">
                            { air.indexName && <span>{ air.indexName }</span> }
                            { air.localIndex && air.universalIndex && air.localIndex.code !== air.universalIndex.code && (
                              <span><strong>Universal AQI</strong> { air.universalIndex.aqiDisplay || Math.round( air.universalIndex.aqi ) }</span>
                            ) }
                            { air.dominant && (
                              <span><strong>Dominant</strong> { dominantPollutantLabel( air.dominant, air.pollutants ) }</span>
                            ) }
                            { air.updatedAt && <span>{ relativeAgeLabel( air.updatedAt ).label }</span> }
                          </div>
                        </div>
                      </div>

                      { air.pollutants.length > 0 && (
                        <div className="vl-live-air-pollutants">
                          <h4 className="vl-live-air-pollutants-title">Pollutants</h4>
                          <ul className="vl-live-air-pollutant-list">
                            { air.pollutants.map( p => (
                              <li className="vl-live-air-pollutant-row" key={ p.code }>
                                <span className="vl-live-air-pollutant-label">{ p.label }</span>
                                <span className="vl-live-air-pollutant-value">{ Math.round( p.value ) } <small>{ p.unit }</small></span>
                                <button
                                  type="button"
                                  className="vl-live-air-pollutant-info"
                                  aria-label={ `${p.label} details` }
                                  aria-expanded={ pollutantTip?.code === p.code }
                                  aria-haspopup="dialog"
                                  aria-describedby={ pollutantTip?.code === p.code ? `vl-live-air-pollutant-tip-${p.code}` : undefined }
                                  onMouseEnter={ e => openPollutantTip( p.code, e.currentTarget ) }
                                  onFocus={ e => openPollutantTip( p.code, e.currentTarget ) }
                                  onClick={ e => openPollutantTip( p.code, e.currentTarget ) }
                                >
                                  <svg viewBox="0 -960 960 960" aria-hidden="true">
                                    <path d={ MATERIAL_SYMBOL_PATHS.info } />
                                  </svg>
                                </button>
                              </li>
                            ) ) }
                          </ul>
                        </div>
                      ) }

                      {/* SECTION 1 - HEATMAP. The atmospheric layer stays part of the
                          live map and no longer has a second Storm switch. This control keeps the
                          same real Google AQI tile behavior, using the exact Material Symbols
                          "switches" glyph requested for the control. */}
                      <div className="vl-live-air-heatmap">
                        <div className="vl-live-air-heatmap-row">
                          <span className="vl-live-air-heatmap-label">Heatmap</span>
                          <div className="vl-live-air-heatmap-control">
                            <div className="vl-live-air-range" role="group" aria-label="Heatmap metric">
                              { ( [ 'AQI', 'PM25' ] as const ).map( metric => (
                                <button
                                  key={ metric }
                                  type="button"
                                  className={ heatmapMetric === metric ? 'is-active' : '' }
                                  aria-pressed={ heatmapMetric === metric }
                                  onClick={ () => { setHeatmapMetric( metric ); setLayer( metric ); } }
                                >
                                  { metric === 'AQI' ? 'AQI' : 'PM2.5' }
                                </button>
                              ) ) }
                            </div>
                            <span className="vl-live-air-heatmap-state" aria-hidden="true">{ layer ? 'On' : 'Off' }</span>
                            <button
                              type="button"
                              role="switch"
                              aria-checked={ Boolean( layer ) }
                              aria-label="Air quality heatmap"
                              disabled={ !hasSelection }
                              className={ `vl-live-air-heatmap-switch ${layer ? 'is-on' : ''}`.trim() }
                              onClick={ () => setLayer( v => v ? null : heatmapMetric ) }
                            >
                              <svg viewBox="0 -960 960 960" aria-hidden="true">
                                <path d={ MATERIAL_SYMBOL_PATHS.switches } />
                              </svg>
                            </button>
                          </div>
                        </div>
                        <div className={ `vl-live-air-heatmap-legend is-${heatmapMetric.toLowerCase()}` }>
                          <span className="vl-live-air-heatmap-ramp" aria-hidden="true" />
                          <span className="vl-live-air-heatmap-ends">
                            <span className="vl-live-air-heatmap-end">{ heatmapMetric === 'AQI' ? 'Poor' : 'Higher' }</span>
                            <span className="vl-live-air-heatmap-end">{ heatmapMetric === 'AQI' ? 'Excellent' : 'Lower' }</span>
                          </span>
                        </div>
                      </div>

                      <div className="vl-live-air-forecast">
                        <div className="vl-live-air-forecast-head">
                          <h4 className="vl-live-air-forecast-title">Air Forecast</h4>
                          <div className="vl-live-air-range" role="group" aria-label="Air forecast range">
                            { ( [ 24, 48, 96 ] as const ).map( hours => (
                              <button key={ hours } type="button" className={ airForecastHours === hours ? 'is-active' : '' } aria-pressed={ airForecastHours === hours } onClick={ () => setAirForecastHours( hours ) }>
                                { hours }h
                              </button>
                            ) ) }
                          </div>
                        </div>
                        { airForecast.length ? (
                          <>
                            <div className="vl-live-air-forecast-strip" aria-label={ `Next ${airForecastHours} hours air forecast` }>
                              { airForecast.slice( 0, airForecastHours ).map( ( point, idx ) => (
                                <button key={ point.time } type="button" className={ `vl-live-air-forecast-card ${airForecastInspectIdx === idx ? 'is-active' : ''}`.trim() } aria-pressed={ airForecastInspectIdx === idx } onClick={ () => setAirForecastInspectIdx( idx ) }>
                                  <span>{ formatHistoryPointLabel( point.time, locationTime.timeZoneId, locationZoneLabel ) }</span>
                                  <strong>AQI { point.aqi }</strong>
                                  { Number.isFinite( point.pm25 ) && <small>PM2.5 { Math.round( point.pm25 as number ) } µg/m³</small> }
                                </button>
                              ) ) }
                            </div>
                            { airForecast[ airForecastInspectIdx ] && (
                              <div className="vl-live-air-forecast-detail">
                                { airForecast[ airForecastInspectIdx ].dominant && (
                                  <span><strong>Dominant</strong> { POLLUTANT_LABELS[ airForecast[ airForecastInspectIdx ].dominant as string ] || airForecast[ airForecastInspectIdx ].dominant }</span>
                                ) }
                                { airForecast[ airForecastInspectIdx ].localAqi != null && airForecast[ airForecastInspectIdx ].universalAqi != null && (
                                  <span><strong>Local / Universal</strong> { airForecast[ airForecastInspectIdx ].localAqi } / { airForecast[ airForecastInspectIdx ].universalAqi }</span>
                                ) }
                                { airForecast[ airForecastInspectIdx ].healthRecommendations?.generalPopulation && (
                                  <p>{ airForecast[ airForecastInspectIdx ].healthRecommendations?.generalPopulation }</p>
                                ) }
                                { ( () => {
                                  const point = airForecast[ airForecastInspectIdx ];
                                  const dominant = point.pollutants?.find( pollutant => pollutant.code === point.dominant );
                                  if ( !dominant?.sources && !dominant?.effects ) return null;
                                  return (
                                    <p className="vl-live-air-forecast-additional">
                                      { dominant.sources && <span><strong>Sources</strong> { compactAirInfo( dominant.sources, 120 ) }</span> }
                                      { dominant.effects && <span><strong>Effects</strong> { compactAirInfo( dominant.effects, 120 ) }</span> }
                                    </p>
                                  );
                                } )() }
                              </div>
                            ) }
                          </>
                        ) : (
                          <p className="vl-live-air-history-empty">96-hour air forecast appears here once Google returns forecast data.</p>
                        ) }
                      </div>

                      {/* SECTION 2 - HEALTH RECOMMENDATIONS. Only Google's returned
                          population-specific text is rendered. Missing groups disappear rather than
                          receiving static/fabricated advice. */}
                      { activeHealthPersona && (
                        <div className="vl-live-air-health">
                          <div className="vl-live-air-health-head">
                            <h4 className="vl-live-air-health-title">Health Recommendations</h4>
                            <div className="vl-live-air-health-pager" aria-label="Health recommendation navigation">
                              <button
                                type="button"
                                className="vl-live-air-health-page-btn"
                                aria-label="Previous health recommendation"
                                onClick={ () => { setHealthExpanded( false ); setHealthPersona( i => ( i - 1 + liveHealthPersonas.length ) % liveHealthPersonas.length ); } }
                                disabled={ liveHealthPersonas.length <= 1 }
                              >
                                <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.chevronLeft } /></svg>
                              </button>
                              <button
                                type="button"
                                className="vl-live-air-health-page-btn"
                                aria-label="Next health recommendation"
                                onClick={ () => { setHealthExpanded( false ); setHealthPersona( i => ( i + 1 ) % liveHealthPersonas.length ); } }
                                disabled={ liveHealthPersonas.length <= 1 }
                              >
                                <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.chevronRight } /></svg>
                              </button>
                            </div>
                          </div>
                          <div className="vl-live-air-health-tabs" role="tablist" aria-label="Health recommendation profiles">
                            { liveHealthPersonas.map( ( persona, idx ) => (
                              <button
                                key={ persona.id }
                                type="button"
                                role="tab"
                                id={ `vl-live-air-health-tab-${persona.id}` }
                                aria-controls="vl-live-air-health-panel"
                                aria-selected={ healthPersona === idx }
                                aria-label={ persona.label }
                                title={ persona.label }
                                className={ `vl-live-air-health-tab ${healthPersona === idx ? 'is-active' : ''}`.trim() }
                                onClick={ () => { setHealthExpanded( false ); setHealthPersona( idx ); } }
                              >
                                <span className="vl-live-air-health-icon-wrap" aria-hidden="true">
                                  <svg viewBox="0 -960 960 960" className="vl-live-air-health-icon">
                                    <path d={ MATERIAL_SYMBOL_PATHS[ persona.icon ] } />
                                  </svg>
                                </span>
                              </button>
                            ) ) }
                          </div>
                          <div
                            className="vl-live-air-health-panel"
                            role="tabpanel"
                            id="vl-live-air-health-panel"
                            aria-labelledby={ `vl-live-air-health-tab-${activeHealthPersona.id}` }
                          >
                            <strong className="vl-live-air-health-persona">{ activeHealthPersona.label }</strong>
                            <p className={ `vl-live-air-health-text ${healthNeedsMore && !healthExpanded ? 'is-clamped' : ''}`.trim() }>{ activeHealthPersona.recommendation }</p>
                            { healthNeedsMore && (
                              <button
                                type="button"
                                className="vl-live-air-health-more"
                                aria-expanded={ healthExpanded }
                                onClick={ () => setHealthExpanded( value => !value ) }
                              >
                                { healthExpanded ? 'Less' : 'More' }
                              </button>
                            ) }
                          </div>
                        </div>
                      ) }

                      {/* SECTION 3 - HOURLY HISTORY. Reuses the existing airHistory state and
                          historyRange/aqiCategory helpers. An inline-SVG AQI line chart over the
                          loaded points, weekday gridlines, a pinned current-value bubble and
                          prev/next navigation. The timestamp is rendered in the selected
                          destination's local timezone. When airHistory is empty (every keyless run)
                          an honest shell renders with no fake chart and no spinner. */}
                      <div className="vl-live-air-history">
                        { ( () => {
                          if ( airHistory.length === 0 ) {
                            return (
                              <>
                                <div className="vl-live-air-history-head">
                                  <h4 className="vl-live-air-history-title">Hourly History</h4>
                                  <div className="vl-live-air-range" role="group" aria-label="Air history range">
                                    { ( [ 24, 168, 720 ] as const ).map( hours => (
                                      <button key={ hours } type="button" className={ historyRange === hours ? 'is-active' : '' } aria-pressed={ historyRange === hours } onClick={ () => setHistoryRange( hours ) }>
                                        { hours === 24 ? '24h' : hours === 168 ? '7d' : '30d' }
                                      </button>
                                    ) ) }
                                  </div>
                                </div>
                                <p className="vl-live-air-history-empty">Hourly history appears here once a place is selected.</p>
                              </>
                            );
                          }
                          // Window the points so prev/next can page through ~a day at a time
                          // while keeping the full week in view by default. We render the full
                          // loaded series but shift which point the "current" bubble pins to.
                          const points = airHistory;
                          const maxOffset = Math.max( 0, points.length - 1 );
                          const offset = Math.min( historyOffset, maxOffset );
                          const currentIdx = Math.max( 0, points.length - 1 - offset );
                          const current = points[ currentIdx ];
                          const latest = points[ points.length - 1 ];
                          const stamp = formatHistoryStamp( current.time, locationTime.timeZoneId, locationZoneLabel );

                          // Chart geometry. AQI mapped to a 0-500 vertical scale; x spread
                          // evenly across the loaded points. No external chart library.
                          const W = 300, H = 120, padX = 6, padTop = 20, padBottom = 18;
                          const innerW = W - padX * 2;
                          const innerH = H - padTop - padBottom;
                          const span = Math.max( 1, points.length - 1 );
                          const xAt = ( i: number ) => padX + ( innerW * i ) / span;
                          const yAt = ( aqi: number ) => padTop + innerH * ( 1 - Math.max( 0, Math.min( 1, aqi / 500 ) ) );
                          const linePts = points.map( ( p, i ) => `${xAt( i ).toFixed( 1 )},${yAt( p.aqi ).toFixed( 1 )}` ).join( ' ' );
                          const areaPts = `${padX},${( H - padBottom ).toFixed( 1 )} ${linePts} ${( W - padX ).toFixed( 1 )},${( H - padBottom ).toFixed( 1 )}`;
                          const cx = xAt( currentIdx );
                          const cy = yAt( current.aqi );
                          const inspectedIdx = historyInspectIdx == null
                            ? null
                            : Math.max( 0, Math.min( historyInspectIdx, points.length - 1 ) );
                          const inspected = inspectedIdx == null ? null : points[ inspectedIdx ];
                          const inspectX = inspectedIdx == null ? 0 : xAt( inspectedIdx );
                          const inspectY = inspected ? yAt( inspected.aqi ) : 0;
                          const inspectPoint = ( clientX: number, target: HTMLElement ) => {
                            const rect = target.getBoundingClientRect();
                            const ratio = rect.width > 0 ? clamp( ( clientX - rect.left ) / rect.width, 0, 1 ) : 0;
                            setHistoryInspectIdx( Math.round( ratio * ( points.length - 1 ) ) );
                          };

                          // Weekday gridlines follow the selected destination's local timezone,
                          // matching the timestamp above instead of mixing local context with UTC.
                          const dayLabel = new Intl.DateTimeFormat( 'en-US', { timeZone: locationTime.timeZoneId, weekday: 'short' } );
                          const dayKey = new Intl.DateTimeFormat( 'en-CA', { timeZone: locationTime.timeZoneId, year: 'numeric', month: '2-digit', day: '2-digit' } );
                          const ticks: { x: number; label: string }[] = [];
                          let lastDay = '';
                          points.forEach( ( p, i ) => {
                            const date = new Date( p.time );
                            const key = dayKey.format( date );
                            if ( key !== lastDay ) {
                              ticks.push( { x: xAt( i ), label: dayLabel.format( date ) } );
                              lastDay = key;
                            }
                          } );

                          return (
                            <>
                              <div className="vl-live-air-history-head">
                                <h4 className="vl-live-air-history-title">Hourly History</h4>
                                <div className="vl-live-air-history-head-meta">
                                  <div className="vl-live-air-range" role="group" aria-label="Air history range">
                                    { ( [ 24, 168, 720 ] as const ).map( hours => (
                                      <button key={ hours } type="button" className={ historyRange === hours ? 'is-active' : '' } aria-pressed={ historyRange === hours } onClick={ () => setHistoryRange( hours ) }>
                                        { hours === 24 ? '24h' : hours === 168 ? '7d' : '30d' }
                                      </button>
                                    ) ) }
                                  </div>

                                  <span className="vl-live-air-history-stamp">{ stamp }</span>
                                  <div className="vl-live-air-history-nav" aria-label="Hourly history navigation">
                                    <button
                                      type="button"
                                      aria-label="Earlier hour"
                                      disabled={ offset >= maxOffset }
                                      onClick={ () => { setHistoryInspectIdx( null ); setHistoryOffset( o => Math.min( maxOffset, o + 1 ) ); } }
                                    >
                                      <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.chevronLeft } /></svg>
                                    </button>
                                    <button
                                      type="button"
                                      aria-label="Later hour"
                                      disabled={ offset <= 0 }
                                      onClick={ () => { setHistoryInspectIdx( null ); setHistoryOffset( o => Math.max( 0, o - 1 ) ); } }
                                    >
                                      <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.chevronRight } /></svg>
                                    </button>
                                  </div>
                                </div>
                              </div>
                              <div
                                className={ `vl-live-air-history-chart vl-live-air-sev-${aqiCategory( current.aqi ).sev}` }
                                role="img"
                                aria-label={ `AQI history, ${historyRangeLabel( historyRange )}, current ${Math.round( current.aqi )}. Hover or tap the chart to inspect an hour.` }
                                onPointerMove={ e => {
                                  if ( e.pointerType === 'mouse' || e.pointerType === 'pen' ) inspectPoint( e.clientX, e.currentTarget );
                                } }
                                onPointerDown={ e => inspectPoint( e.clientX, e.currentTarget ) }
                                onPointerLeave={ e => {
                                  if ( e.pointerType === 'mouse' ) setHistoryInspectIdx( null );
                                } }
                              >
                                <svg viewBox={ `0 0 ${W} ${H}` } className="vl-live-air-history-svg" preserveAspectRatio="none">
                                  { ticks.map( ( t, i ) => (
                                    <g key={ `${t.label}-${i}` }>
                                      <line className="vl-live-air-history-grid" x1={ t.x } y1={ padTop } x2={ t.x } y2={ H - padBottom } />
                                      <text className="vl-live-air-history-day" x={ t.x + 2 } y={ H - 5 }>{ t.label }</text>
                                    </g>
                                  ) ) }
                                  <polygon className="vl-live-air-history-area" points={ areaPts } />
                                  <polyline className="vl-live-air-history-line" points={ linePts } />
                                  <line className="vl-live-air-history-leader" x1={ cx } y1={ padTop } x2={ cx } y2={ cy } />
                                  <circle className="vl-live-air-history-dot" cx={ cx } cy={ cy } r="4" />
                                  { inspected && (
                                    <>
                                      <line className="vl-live-air-history-inspect-line" x1={ inspectX } y1={ padTop } x2={ inspectX } y2={ inspectY } />
                                      <circle className="vl-live-air-history-inspect-dot" cx={ inspectX } cy={ inspectY } r="5" />
                                    </>
                                  ) }
                                </svg>
                                <span className="vl-live-air-history-bubble" style={ { left: `${( cx / W ) * 100}%` } }>{ Math.round( current.aqi ) }</span>
                                { inspected && (
                                  <span
                                    className="vl-live-air-history-inspect"
                                    role="status"
                                    aria-live="polite"
                                    style={ {
                                      left: `${( inspectX / W ) * 100}%`,
                                      top: `${Math.max( 10, ( inspectY / H ) * 100 )}%`,
                                    } }
                                  >
                                    <strong>AQI { Math.round( inspected.aqi ) }</strong>
                                    <span>{ formatHistoryPointLabel( inspected.time, locationTime.timeZoneId, locationZoneLabel ) }</span>
                                  </span>
                                ) }
                              </div>
                              <span className="vl-live-sr-only">Latest reading { Math.round( latest.aqi ) }, { latest.word }.</span>
                            </>
                          );
                        } )() }
                      </div>
                    </div>
                  ) : (
                    <div className="vl-live-air-panel" role="tabpanel" id="vl-live-air-panel" aria-labelledby="vl-live-air-tab" aria-label="Air details">
                      <p className="vl-live-air-empty">Live air quality appears here once a place is selected.</p>
                    </div>
                  )
                ) }

                { detailTab === 'weather' && (
                  <div className="vl-live-air-panel" role="tabpanel" id="vl-live-weather-panel" aria-labelledby="vl-live-weather-tab" aria-label="Weather details">
                    <p className="vl-live-air-empty">Weather details are coming soon.</p>
                  </div>
                ) }

              </aside>
              </div>

              { ( !mapActive || mapFailed ) ? (
                /* MAP-FREE FALLBACK. This branch used to render an eager
                   maps.google.com/maps?...&output=embed iframe. On a public page that is an
                   UNCONSENTED third-party request to Google on every keyless or map-failed visit,
                   and under output:'export' a keyless build shipped it to every visitor. Removed
                   as an owner-approved privacy fix. The placeholder is self-contained: no src, no
                   href, no remote background - it only restates place state the component already
                   holds. The REAL map path below (Maps JS injection guarded by `if(!MAPS_KEY)`,
                   .vl-live-map-canvas) and every Air/Weather call are UNCHANGED. */
                <div className="vl-live-map-placeholder" role="status">
                  <strong>{ previewPlace.name || 'Lumpyngngad' }</strong>
                  { previewPlace.addr && <span>{ previewPlace.addr }</span> }
                  <p>{ mapActive ? 'Interactive map could not load' : 'Interactive map unavailable' }</p>
                </div>
              ) : (
                <>
                  { !mapReady && (
                    <div className="vl-live-map-fallback" role="status">
                      <span>Loading map…</span>
                    </div>
                  ) }
                  <div className={ `vl-live-map-canvas ${mapReady ? 'is-ready' : ''}` } ref={ mapHost } role="img" aria-label={ hasSelection ? `Map of ${place.name}` : 'Interactive world map' } />
                  { mapReady && (
                    <div ref={ atmosphereRef } className="vl-live-atmosphere" style={ atmosphereStyle } aria-hidden="true">
                      <svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice">
                        <defs>
                          <filter id="vl-live-cloud-soft" x="-25%" y="-25%" width="150%" height="150%">
                            <feGaussianBlur stdDeviation="34" />
                          </filter>
                          <filter id="vl-live-wind-soft" x="-10%" y="-10%" width="120%" height="120%">
                            <feGaussianBlur stdDeviation=".55" />
                          </filter>
                        </defs>

                        <g className="vl-live-cloud-field" filter="url(#vl-live-cloud-soft)">
                          <ellipse cx="120" cy="170" rx="250" ry="82" />
                          <ellipse cx="390" cy="130" rx="230" ry="76" />
                          <ellipse cx="650" cy="118" rx="280" ry="88" />
                          <ellipse cx="965" cy="155" rx="250" ry="82" />
                          <ellipse cx="1260" cy="118" rx="300" ry="98" />
                          <ellipse className="is-dim" cx="1450" cy="260" rx="210" ry="90" />
                          <ellipse className="is-dim" cx="210" cy="640" rx="245" ry="110" />
                          <ellipse cx="505" cy="690" rx="270" ry="94" />
                          <ellipse className="is-dim" cx="930" cy="720" rx="285" ry="102" />
                          <ellipse cx="1320" cy="650" rx="310" ry="118" />
                        </g>

                        <g className="vl-live-wind-field" filter="url(#vl-live-wind-soft)">
                          <path className="vl-live-wind-path p1" d="M-120 610 C120 520 300 535 500 625 S860 760 1120 640 S1450 520 1720 610" />
                          <path className="vl-live-wind-path p2" d="M-80 690 C150 610 350 630 535 715 S900 815 1160 710 S1450 625 1680 690" />
                          <path className="vl-live-wind-path p3" d="M-60 520 C160 445 360 455 565 535 S930 655 1200 540 S1470 460 1690 525" />
                          <path className="vl-live-wind-path p4" d="M-90 400 C130 330 330 340 520 420 S860 520 1090 430 S1410 330 1700 405" />
                          <path className="vl-live-wind-path p5" d="M-60 300 C190 235 385 250 590 320 S950 405 1190 320 S1450 245 1690 300" />
                          <path className="vl-live-wind-path p6" d="M-40 785 C210 720 410 735 610 805 S980 860 1210 800 S1455 730 1660 775" />
                          <path className="vl-live-wind-path p7" d="M20 210 C250 150 480 175 665 240 S1010 315 1250 235 S1470 165 1620 205" />
                        </g>

                        <g className="vl-live-vortex">
                          <ellipse cx="295" cy="680" rx="156" ry="92" />
                          <ellipse cx="295" cy="680" rx="112" ry="66" />
                          <ellipse cx="295" cy="680" rx="70" ry="40" />
                          <path d="M122 680 C172 555 355 535 444 635 C520 720 412 819 294 786 C215 764 214 694 288 670 C341 654 372 701 340 731" />
                        </g>
                      </svg>
                    </div>
                  ) }
                </>
              ) }



            </div>
          </section>
        </div>
      </main>

      { pollutantTip && activePollutant && (
        <div
          className={ `vl-live-air-pollutant-tip is-${pollutantTip.side}` }
          id={ `vl-live-air-pollutant-tip-${activePollutant.code}` }
          role="dialog"
          aria-modal="false"
          aria-label={ `${activePollutant.label} pollutant details` }
          style={ { top: pollutantTip.top, left: pollutantTip.left } }
        >
          <div className="vl-live-air-pollutant-pop">
            <div className="vl-live-air-pollutant-pop-head">
              <span>
                <span className="vl-live-air-pollutant-pop-title">{ activePollutant.label }</span>
                { activePollutant.fullName && <span className="vl-live-air-pollutant-pop-fullname">{ activePollutant.fullName }</span> }
              </span>
              <button
                type="button"
                className="vl-live-air-pollutant-pop-close"
                aria-label="Close pollutant details"
                onClick={ () => setPollutantTip( null ) }
              >
                <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.close } /></svg>
              </button>
            </div>
            { activePollutant.sources && (
              <div className="vl-live-air-pollutant-pop-line is-source">
                <strong>Sources</strong>
                <span>{ compactAirInfo( activePollutant.sources ) }</span>
              </div>
            ) }
            { activePollutant.effects && (
              <div className="vl-live-air-pollutant-pop-line is-effect">
                <strong>Effects</strong>
                <span>{ compactAirInfo( activePollutant.effects ) }</span>
              </div>
            ) }
            { !activePollutant.sources && !activePollutant.effects && (
              <div className="vl-live-air-pollutant-pop-text">
                { `${activePollutant.label}: ${Math.round( activePollutant.value )} ${activePollutant.unit}` }
              </div>
            ) }
          </div>
        </div>
      ) }
      <style jsx>{`
        .vl-live{
          --page:#fff;--alt:#fafafa;--lime:#d1f470;--lime-hover:#c5e866;--lime-tint:rgba(209,244,112,.22);
          --green:#1a3a2a;--hair:#e5e7eb;--heading:rgba(0,0,0,.95);--body:rgba(0,0,0,.898);
          --muted:rgba(0,0,0,.54);--status:rgba(0,0,0,.70);--panel-r:14px;--pill-r:999px;
          /* Shared VayuLok UI system, pinned to the homepage card/body ladder. */
          --vl-card-heading-size:22px;--vl-card-heading-weight:700;--vl-card-heading-lh:1.27;--vl-card-heading-track:-.25px;
          --vl-body-size:20px;--vl-body-weight:400;--vl-body-lh:1.4;--vl-body-track:-.125px;
          --vl-section-gap:24px;--vl-section-pad:20px;--vl-heading-gap:14px;--vl-content-gap:16px;--vl-action-size:36px;
          font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:var(--body);background:var(--page);padding-bottom:72px;-webkit-font-smoothing:antialiased;
        }
        .vl-live,.vl-live *{box-sizing:border-box}
        .vl-live button,.vl-live input{font:inherit}
        .vl-live button{cursor:pointer}
        .vl-live button:focus-visible{outline:3px solid var(--green);outline-offset:3px}
        .vl-live input:focus-visible{outline:none}
        .vl-live-sr,.vl-live-sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
        .vl-live-shell{max-width:1320px;margin:0 auto;padding:0 max(24px,env(safe-area-inset-right)) max(72px,env(safe-area-inset-bottom)) max(24px,env(safe-area-inset-left))}
        /* The map is now the full-width backdrop; the former two-column workspace
           collapses to a single region that the map shell fills edge to edge. */
        .vl-live-workspace{display:block}
        .vl-live-map-region{min-width:0}

        /* ── FLOATING AIR QUALITY CARD ───────────────────────────────────────────────
           A white, rounded, home-system card floating over the full-bleed map's top-left corner,
           inset so it clears Google's bottom-left logo and bottom-right legal notices.
           Scrollable so a long pollutant list never spills past the map. NO red. */
        .vl-live-air-card-wrap{position:relative;z-index:12;grid-area:1/1;align-self:start;justify-self:start;width:min(416px,calc(100% - 32px));margin:16px 0 112px 16px;filter:drop-shadow(0 8px 18px rgba(26,58,42,.10))}
        .vl-live-air-card{position:relative;width:100%;overflow:visible;padding:24px;border:1px solid var(--hair);border-radius:14px;background:#fff;box-shadow:none;color:var(--body)}

        .vl-live-air-context{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 18px;padding:0 0 16px;border-bottom:1px solid var(--hair)}
        .vl-live-air-context-item{display:inline-flex;min-width:0;align-items:center;gap:9px;color:var(--status);font-size:12px;line-height:1.25}
        .vl-live-air-context-item svg{flex:0 0 var(--vl-action-size);width:var(--vl-action-size);height:var(--vl-action-size);padding:7px;border-radius:50%;background:var(--lime);fill:var(--green)}
        .vl-live-air-context-item strong{min-width:0;overflow:hidden;color:var(--heading);font-size:15px;font-weight:700;line-height:1.25;text-overflow:ellipsis;white-space:nowrap}
        .vl-live-air-context-item.is-time{justify-content:flex-end;white-space:nowrap}
        .vl-live-air-context-item time{color:var(--heading);font-weight:700}
        .vl-live-air-context-item small{color:var(--muted);font-size:11px;font-weight:600}

        /* Air/Weather toggle - same pale tint + saturated same-hue dot as the hero pill. */
        .vl-live-air-toggle{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:3px;border:1px solid var(--hair);border-radius:var(--pill-r);background:#fff}
        .vl-live-air-toggle-btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:40px;border:0;border-radius:var(--pill-r);background:transparent;color:var(--green);font-size:16px;font-weight:700;letter-spacing:-.15px}
        .vl-live-air-toggle-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:rgba(26,58,42,.3)}
        .vl-live-air-toggle-btn.is-air.is-active{background:#e0f7c8}
        .vl-live-air-toggle-btn.is-air.is-active .vl-live-air-toggle-dot{background:#3da35a}
        .vl-live-air-toggle-btn.is-weather.is-active{background:#dbeafe;color:#1e3a5f}
        .vl-live-air-toggle-btn.is-weather.is-active .vl-live-air-toggle-dot{background:#2563eb}

        .vl-live-air-panel{margin-top:16px}
        .vl-live-air-empty{margin:0;padding:14px 0;color:var(--muted);font-size:12.5px;line-height:1.5}
        .vl-live-air-gauge-label{margin:0 0 10px;color:var(--green);font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
        .vl-live-air-gauge-row{display:grid;grid-template-columns:4px auto minmax(0,1fr);align-items:center;gap:14px}
        /* HOME-PAGE HUE SPINE, not an AQI severity encoding. These are the exact three
           accent bars used by .home-flow-list: green / blue / purple. The AQI number +
           category text carry the meaning, so the decorative hue never has to be decoded. */
        .vl-live-air-aqi-spine{display:block;width:4px;height:64px;border-radius:999px;background:linear-gradient(180deg,#3da35a 0 33.333%,#2563eb 33.333% 66.666%,#9849e8 66.666% 100%)}
        .vl-live-air-aqi-score{display:flex;min-width:56px;flex-direction:column;align-items:flex-start;justify-content:center}
        .vl-live-air-aqi-number{display:block;color:#000;font-size:30px;font-weight:700;line-height:1;letter-spacing:-.6px}
        .vl-live-air-aqi-unit{display:block;margin-top:4px;color:var(--muted);font-size:10.5px;font-weight:700;line-height:1;letter-spacing:.08em;text-transform:uppercase}
        .vl-live-air-gauge-meta{min-width:0}
        .vl-live-air-gauge-word{display:block;color:#000;font-size:var(--vl-card-heading-size);font-weight:var(--vl-card-heading-weight);line-height:var(--vl-card-heading-lh);letter-spacing:var(--vl-card-heading-track)}
        .vl-live-air-summary-meta{display:flex;flex-wrap:wrap;align-items:center;gap:5px 10px;margin-top:8px;color:var(--muted);font-size:11.5px;font-weight:600;line-height:1.35}
        .vl-live-air-summary-meta span+span::before{content:"·";margin-right:10px;color:rgba(0,0,0,.28)}
        .vl-live-air-summary-meta strong{color:var(--status);font-weight:700}

        .vl-live-air-pollutants,.vl-live-air-heatmap,.vl-live-air-forecast,.vl-live-air-health,.vl-live-air-history{margin-top:var(--vl-section-gap);padding-top:var(--vl-section-pad);border-top:1px solid var(--hair)}
        .vl-live-air-pollutants-title,.vl-live-air-heatmap-label,.vl-live-air-forecast-title,.vl-live-air-health-title,.vl-live-air-history-title{display:block;margin:0;color:#000;font-size:var(--vl-card-heading-size);font-weight:var(--vl-card-heading-weight);line-height:var(--vl-card-heading-lh);letter-spacing:var(--vl-card-heading-track);padding-left:10px;border-left:3px solid var(--lime)}
        .vl-live-air-pollutants-title{margin-bottom:var(--vl-heading-gap)}
        /* overflow:visible (was hidden) so the side popover below can escape the list box
           and float beside its row without being clipped. The list keeps its rounded 12px
           frame; the first/last rows round their own outer corners so the row fills still
           follow the frame now that the list no longer clips them. No scrollbar colour and
           no scrollbar hider are introduced here (the card keeps only scrollbar-width:thin). */
        .vl-live-air-pollutant-list{margin:0;padding:0;list-style:none;border:1px solid var(--hair);border-radius:12px;overflow:visible}
        .vl-live-air-pollutant-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(118px,auto) var(--vl-action-size);align-items:center;gap:var(--vl-content-gap);padding:14px 14px;background:#fff;border-left:2px solid transparent;transition:background .15s ease,border-color .15s ease}
        .vl-live-air-pollutant-row:first-child{border-top-left-radius:11px;border-top-right-radius:11px}
        .vl-live-air-pollutant-row:last-child{border-bottom-left-radius:11px;border-bottom-right-radius:11px}
        .vl-live-air-pollutant-row+.vl-live-air-pollutant-row{border-top:1px solid var(--hair)}
        .vl-live-air-pollutant-value{justify-self:end;min-width:118px;color:#000;font-size:17px;font-weight:700;line-height:1.25;letter-spacing:-.2px;text-align:right;font-variant-numeric:tabular-nums}
        .vl-live-air-pollutant-value small{margin-left:4px;color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0}
        .vl-live-air-pollutant-label{min-width:0;color:var(--body);font-size:17px;font-weight:700;line-height:1.25;letter-spacing:-.18px}
        /* ONE ACTION-ICON SYSTEM for the Air card. Every clickable icon uses the same
           36px circle, lime surface, deep-green glyph, lighter-lime hover and focus ring.
           No hover border, no dark-green hover fill, no inversion, no section-specific skin. */
        .vl-live-air-pollutant-info,
        .vl-live-air-heatmap-switch,
        .vl-live-air-pollutant-pop-close,
        .vl-live-air-health-page-btn,
        .vl-live-air-health-tab,
        .vl-live-air-history-nav button{display:inline-flex;align-items:center;justify-content:center;flex:0 0 var(--vl-action-size);width:var(--vl-action-size);height:var(--vl-action-size);padding:0;border:0;border-radius:50%;background:var(--lime);color:var(--green);box-shadow:none;transition:background-color .2s,transform .16s ease,box-shadow .16s ease;color-scheme:light}
        .vl-live-air-pollutant-info,
        .vl-live-air-heatmap-switch,
        .vl-live-air-pollutant-pop-close,
        .vl-live-air-health-page-btn,
        .vl-live-air-health-tab{transition:background-color .2s,transform .16s ease,box-shadow .16s ease}
        .vl-live-air-pollutant-info{cursor:help}
        .vl-live-air-pollutant-info:hover,
        .vl-live-air-heatmap-switch:hover:not(:disabled),
        .vl-live-air-pollutant-pop-close:hover,
        .vl-live-air-health-page-btn:hover:not(:disabled),
        .vl-live-air-health-tab:hover,
        .vl-live-air-history-nav button:hover:not(:disabled){background:var(--lime-hover);color:var(--green);border:0;box-shadow:0 6px 14px rgba(26,58,42,.16);transform:translateY(-2px) scale(1.04)}
        .vl-live-air-pollutant-info:focus-visible,
        .vl-live-air-heatmap-switch:focus-visible,
        .vl-live-air-pollutant-pop-close:focus-visible,
        .vl-live-air-health-page-btn:focus-visible,
        .vl-live-air-health-tab:focus-visible,
        .vl-live-air-history-nav button:focus-visible{outline:3px solid var(--green);outline-offset:2px}
        .vl-live-air-pollutant-info svg,
        .vl-live-air-heatmap-switch svg,
        .vl-live-air-pollutant-pop-close svg,
        .vl-live-air-health-page-btn svg,
        .vl-live-air-health-tab svg,
        .vl-live-air-history-nav button svg{width:21px;height:21px;fill:currentColor}
        .vl-live-air-heatmap-switch:disabled,
        .vl-live-air-health-page-btn:disabled,
        .vl-live-air-history-nav button:disabled{opacity:.4;cursor:not-allowed}

        /* Fixed sibling OUTSIDE the scrollable Air card: white home-page surface, compact copy,
           viewport-clamped position and an explicit close affordance. Lime is an accent only,
           never the popup background. The directional notch is shape-only reference language. */
        .vl-live-air-pollutant-tip{position:fixed;z-index:2200;width:min(320px,calc(100vw - 24px));max-height:min(240px,calc(100dvh - 24px));overflow:auto;padding:16px;border:1px solid var(--hair);border-top:3px solid var(--lime);border-radius:14px;background:#fff;color:var(--body);box-shadow:0 14px 34px rgba(26,58,42,.16);font-size:13px;line-height:1.42;text-align:left}
        .vl-live-air-pollutant-tip::before{content:"";position:absolute;width:12px;height:12px;background:#fff}
        .vl-live-air-pollutant-tip.is-right::before{left:-7px;top:30px;transform:rotate(45deg);border-left:1px solid var(--hair);border-bottom:1px solid var(--hair)}
        .vl-live-air-pollutant-tip.is-left::before{right:-7px;top:30px;transform:rotate(45deg);border-top:1px solid var(--hair);border-right:1px solid var(--hair)}
        .vl-live-air-pollutant-tip.is-bottom::before{top:-7px;left:50%;transform:translateX(-50%) rotate(45deg);border-left:1px solid var(--hair);border-top:1px solid var(--hair)}
        .vl-live-air-pollutant-tip.is-top::before{bottom:-7px;left:50%;transform:translateX(-50%) rotate(45deg);border-right:1px solid var(--hair);border-bottom:1px solid var(--hair)}
        .vl-live-air-pollutant-pop{display:flex;flex-direction:column;gap:11px}
        .vl-live-air-pollutant-pop-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
        .vl-live-air-pollutant-pop-title{display:inline-flex;min-height:28px;align-items:center;padding:0 10px;border:1px solid var(--hair);border-radius:999px;background:#f7f7f5;color:var(--green);font-size:13px;font-weight:700;letter-spacing:-.1px}
        .vl-live-air-pollutant-pop-fullname{display:block;margin-top:5px;color:var(--muted);font-size:11.5px;font-weight:600;line-height:1.3}
        .vl-live-air-pollutant-pop-line{display:grid;grid-template-columns:64px 1fr;gap:10px;align-items:start}
        .vl-live-air-pollutant-pop-line strong{font-size:12.5px;font-weight:700;letter-spacing:.01em}
        .vl-live-air-pollutant-pop-line span{color:var(--status);font-size:13px;font-weight:400;line-height:1.42}
        .vl-live-air-pollutant-pop-line.is-source strong{color:#2563eb}
        .vl-live-air-pollutant-pop-line.is-effect strong{color:#9849e8}
        .vl-live-air-pollutant-pop-text{color:var(--status);font-size:13px;line-height:1.42}
        .vl-live-air-pollutant-row:focus-within,.vl-live-air-pollutant-row:hover{background:rgba(209,244,112,.18);border-left-color:var(--lime)}

        /* ── HEATMAP ──────────────────────────────────────────────────────────────
           One compact Material Symbols control; the separate Storm switch is intentionally gone. */
        .vl-live-air-heatmap-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:var(--vl-heading-gap)}
        .vl-live-air-heatmap-control{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}
        .vl-live-air-heatmap-state{color:var(--muted);font-size:11.5px;font-weight:700;line-height:1}
        .vl-live-air-heatmap-switch.is-on{background:var(--lime-hover);color:var(--green)}
        .vl-live-air-heatmap-legend{margin-top:0}
        .vl-live-air-heatmap-ramp{display:block;height:8px;border-radius:999px;background:linear-gradient(90deg,#c98a2e 0%,#e8c547 42%,#d1f470 74%,#3da35a 100%)}
        .vl-live-air-heatmap-legend.is-pm25 .vl-live-air-heatmap-ramp{background:linear-gradient(90deg,#9849e8 0%,#2563eb 100%)}
        .vl-live-air-heatmap-ends{display:flex;align-items:center;justify-content:space-between;margin-top:6px}
        .vl-live-air-heatmap-end{color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.02em}
        .vl-live-air-range{display:inline-flex;align-items:center;gap:4px;padding:2px;border-radius:999px;background:#f4f5f1}
        .vl-live-air-range button{min-height:28px;padding:0 9px;border:0;border-radius:999px;background:transparent;color:var(--muted);font-size:11px;font-weight:700;line-height:1}
        .vl-live-air-range button.is-active{background:var(--lime);color:var(--green)}
        .vl-live-air-range button:hover{background:var(--lime-hover);color:var(--green)}
        .vl-live-air-forecast-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:var(--vl-heading-gap)}
        .vl-live-air-forecast-strip{display:flex;gap:8px;overflow-x:auto;padding:0 0 6px;scroll-snap-type:x proximity;scrollbar-width:none}
        .vl-live-air-forecast-strip::-webkit-scrollbar{display:none}
        .vl-live-air-forecast-card{display:flex;flex:0 0 122px;scroll-snap-align:start;flex-direction:column;align-items:flex-start;gap:4px;padding:10px;border:1px solid var(--hair);border-radius:10px;background:#fff;color:var(--body);text-align:left}
        .vl-live-air-forecast-card:hover,.vl-live-air-forecast-card.is-active{border-color:var(--lime);background:var(--lime-tint)}
        .vl-live-air-forecast-card span{color:var(--muted);font-size:10.5px;font-weight:600;line-height:1.25}
        .vl-live-air-forecast-card strong{color:#000;font-size:15px;font-weight:700;line-height:1.2}
        .vl-live-air-forecast-card small{color:var(--status);font-size:10.5px;font-weight:600;line-height:1.3}
        .vl-live-air-forecast-detail{display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:10px;color:var(--muted);font-size:11.5px;font-weight:600;line-height:1.4}
        .vl-live-air-forecast-detail strong{color:var(--status);font-weight:700}
        .vl-live-air-forecast-detail p{flex:1 0 100%;margin:2px 0 0;color:var(--body);font-size:14px;font-weight:400;line-height:1.45}
        .vl-live-air-forecast-additional{display:flex;flex-direction:column;gap:4px}
        .vl-live-air-forecast-additional span{display:block}

        /* ── HEALTH RECOMMENDATIONS ──────────────────────────────────────────────
           Icons and arrows inherit the ONE action-icon system above. The row stays horizontal;
           selection uses the lighter-lime surface, never a border/ring. Recommendation type
           follows the home-page heading/body ladder exactly. */
        .vl-live-air-health-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:var(--vl-heading-gap)}
        .vl-live-air-health-pager{display:flex;align-items:center;gap:6px}
        .vl-live-air-health-tabs{display:flex;align-items:center;gap:8px;overflow-x:auto;padding:0 0 4px;scrollbar-width:none;white-space:nowrap}
        .vl-live-air-health-tabs::-webkit-scrollbar{display:none}
        .vl-live-air-health-tab.is-active{background:var(--lime-hover);color:var(--green);box-shadow:none;transform:none}
        .vl-live-air-health-icon-wrap{display:flex;align-items:center;justify-content:center;width:100%;height:100%;border:0;border-radius:inherit;background:transparent;color:inherit}
        .vl-live-air-health-icon{width:21px;height:21px;fill:currentColor}
        .vl-live-air-health-panel{margin-top:var(--vl-content-gap);padding-top:var(--vl-content-gap);border-top:1px solid var(--hair)}
        .vl-live-air-health-persona{display:block;margin:0 0 6px;color:#000;font-size:var(--vl-card-heading-size);font-weight:var(--vl-card-heading-weight);line-height:var(--vl-card-heading-lh);letter-spacing:var(--vl-card-heading-track)}
        .vl-live-air-health-text{margin:0;color:var(--body);font-size:var(--vl-body-size);font-weight:var(--vl-body-weight);line-height:var(--vl-body-lh);letter-spacing:var(--vl-body-track)}
        .vl-live-air-health-text.is-clamped{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:5;overflow:hidden}
        .vl-live-air-health-more{margin-top:8px;padding:0;border:0;background:transparent;color:var(--green);font-size:14px;font-weight:700;line-height:1.3;text-decoration:none;text-underline-offset:3px}
        .vl-live-air-health-more:hover{color:#000;text-decoration:underline}

        /* ── HOURLY HISTORY (inline-SVG AQI chart) ──────────────────────────────────
           Line + area stroked from the no-red ramp via the sev-mapped class; the pinned
           bubble shows the current AQI number so meaning never rests on colour alone. */
        .vl-live-air-history-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:var(--vl-heading-gap)}
        .vl-live-air-history-head-meta{display:flex;align-items:center;gap:8px}
        .vl-live-air-history-stamp{color:var(--muted);font-size:11.5px;font-weight:600;letter-spacing:0;white-space:nowrap}
        .vl-live-air-history-empty{margin:0;color:var(--muted);font-size:14px;line-height:1.5}
        .vl-live-air-history-chart{position:relative;margin-top:0;touch-action:pan-y;cursor:crosshair}
        .vl-live-air-history-svg{display:block;width:100%;height:120px}
        .vl-live-air-history-grid{stroke:var(--hair);stroke-width:1;stroke-dasharray:2 3}
        .vl-live-air-history-day{fill:var(--muted);font-size:8px;font-weight:600}
        .vl-live-air-history-leader{stroke:var(--muted);stroke-width:1;stroke-dasharray:2 2}
        .vl-live-air-history-line{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
        .vl-live-air-history-area{fill:currentColor;opacity:.12;stroke:none}
        .vl-live-air-history-dot{stroke:#fff;stroke-width:2}
        .vl-live-air-history-inspect-line{stroke:rgba(26,58,42,.42);stroke-width:1;stroke-dasharray:2 2}
        .vl-live-air-history-inspect-dot{fill:var(--lime);stroke:var(--green);stroke-width:2}
        .vl-live-air-history-inspect{position:absolute;z-index:2;display:flex;flex-direction:column;gap:2px;max-width:150px;transform:translate(-50%,-112%);padding:6px 8px;border:1px solid var(--hair);border-radius:8px;background:#fff;color:var(--green);box-shadow:0 6px 16px rgba(26,58,42,.12);pointer-events:none;white-space:nowrap}
        .vl-live-air-history-inspect strong{font-size:11.5px;font-weight:700;line-height:1.2}
        .vl-live-air-history-inspect span{color:var(--muted);font-size:10.5px;font-weight:600;line-height:1.2}
        /* The chart colour walks the no-red ramp from the current point's severity. */
        .vl-live-air-sev-good .vl-live-air-history-line,.vl-live-air-sev-good .vl-live-air-history-dot{stroke:#1a3a2a}
        .vl-live-air-sev-good .vl-live-air-history-area{color:#1a3a2a}
        .vl-live-air-sev-sat .vl-live-air-history-line,.vl-live-air-sev-sat .vl-live-air-history-dot{stroke:#3da35a}
        .vl-live-air-sev-sat .vl-live-air-history-area{color:#3da35a}
        .vl-live-air-sev-mod .vl-live-air-history-line,.vl-live-air-sev-mod .vl-live-air-history-dot{stroke:#d1f470}
        .vl-live-air-sev-mod .vl-live-air-history-area{color:#d1f470}
        .vl-live-air-sev-poor .vl-live-air-history-line,.vl-live-air-sev-poor .vl-live-air-history-dot{stroke:#e8c547}
        .vl-live-air-sev-poor .vl-live-air-history-area{color:#e8c547}
        .vl-live-air-sev-worst .vl-live-air-history-line,.vl-live-air-sev-worst .vl-live-air-history-dot{stroke:#c98a2e}
        .vl-live-air-sev-worst .vl-live-air-history-area{color:#c98a2e}
        .vl-live-air-history-bubble{position:absolute;top:0;transform:translateX(-50%);min-width:30px;padding:3px 8px;border:0;border-radius:999px;background:var(--lime);color:var(--green);box-shadow:0 4px 10px rgba(26,58,42,.14);font-size:11px;font-weight:700;text-align:center}
        .vl-live-air-history-nav{display:flex;align-items:center;gap:6px}

        /* FULL-BLEED MAP. The map reads edge-to-edge: no border, no rounded box. overflow:hidden
           still clips the heatmap tiles + overlays, isolation:isolate keeps the overlay z-stack
           contained, and the height band is unchanged. The floating .vl-live-air-card stays
           positioned over the edge-to-edge map, while the card's bottom inset still clears
           Google's bottom-left logo and bottom-right legal corners. */
        .vl-live-map-shell{position:relative;display:grid;height:auto;min-height:min(620px,72svh);max-height:none;overflow:visible;background:#eef1ed;isolation:isolate;contain:layout}
        .vl-live-map-canvas,.vl-live-map-placeholder{position:absolute;inset:0;width:100%;height:100%}
        .vl-live-map-canvas{opacity:0}
        .vl-live-map-canvas.is-ready{opacity:1}

        /* REFERENCE-MATCHED ATMOSPHERE. This is code-rendered, not a background image.
           Clouds are soft translucent SVG masses; wind is a field of animated dashed
           streamlines; the lower-left vortex gives the storm/cyclone read from the approved
           reference. Live Google Weather values drive opacity, direction and speed. */
        .vl-live-atmosphere{--vl-map-shift-x:0px;--vl-map-shift-y:0px;--vl-map-scale:1;position:absolute;inset:0;z-index:4;pointer-events:none;overflow:hidden;mix-blend-mode:screen;transform:translate3d(var(--vl-map-shift-x),var(--vl-map-shift-y),0) scale(var(--vl-map-scale));transform-origin:50% 50%;will-change:transform}
        .vl-live-atmosphere svg{display:block;width:100%;height:100%;overflow:visible}
        .vl-live-cloud-field{opacity:var(--vl-cloud-opacity);animation:vl-live-cloud-drift var(--vl-cloud-duration) ease-in-out infinite alternate}
        .vl-live-cloud-field ellipse{fill:rgba(255,255,255,.88)}
        .vl-live-cloud-field ellipse.is-dim{fill:rgba(214,229,239,.66)}
        .vl-live-wind-field{opacity:var(--vl-wind-opacity);transform-origin:800px 450px;transform:rotate(var(--vl-wind-angle))}
        .vl-live-wind-path{fill:none;stroke:rgba(255,255,255,.86);stroke-width:1.5;stroke-linecap:round;stroke-dasharray:5 17;animation:vl-live-wind-flow var(--vl-wind-duration) linear infinite}
        .vl-live-wind-path.p2{animation-delay:-1.8s;opacity:.82}
        .vl-live-wind-path.p3{animation-delay:-3.1s;opacity:.72}
        .vl-live-wind-path.p4{animation-delay:-4.4s;opacity:.66}
        .vl-live-wind-path.p5{animation-delay:-5.7s;opacity:.58}
        .vl-live-wind-path.p6{animation-delay:-2.6s;opacity:.76}
        .vl-live-wind-path.p7{animation-delay:-4.9s;opacity:.54}
        .vl-live-vortex{opacity:var(--vl-storm-opacity);transform-origin:295px 680px;animation:vl-live-vortex-spin var(--vl-vortex-duration) linear infinite}
        .vl-live-vortex ellipse,.vl-live-vortex path{fill:none;stroke:rgba(255,255,255,.86);stroke-width:2;stroke-linecap:round;stroke-dasharray:8 14}
        @keyframes vl-live-wind-flow{to{stroke-dashoffset:-88}}
        @keyframes vl-live-cloud-drift{from{transform:translate3d(-2.2%,0,0) scale(1.02)}to{transform:translate3d(2.8%,1.2%,0) scale(1.06)}}
        @keyframes vl-live-vortex-spin{to{transform:rotate(360deg)}}
        .vl-live-map-placeholder{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding:24px;text-align:center;z-index:0;background:#eef1ed;color:var(--green)}
        .vl-live-map-placeholder strong{font-size:15px;letter-spacing:-.01em}
        .vl-live-map-placeholder span{font-size:12.5px;color:var(--muted)}
        .vl-live-map-placeholder p{margin:4px 0 0;font-size:12px;color:var(--status)}
        .vl-live-map-fallback{position:absolute;inset:0;display:grid;place-items:center;z-index:0;background:#eef1ed;color:var(--green);font-size:13px}
        .vl-live-map-fallback button{margin-left:8px;border:1px solid var(--green);border-radius:999px;background:#fff;color:var(--green);padding:7px 11px}
        /* DESTINATION SEARCH is a separate page section ABOVE the map shell. Its outer
           wrapper is deliberately invisible: the only visible field chrome is the same
           bottom hairline used by Header .nav-search and ProductBlogPanel .pbp-search. */
        .vl-live-map-search{position:relative;z-index:30;width:min(760px,calc(100% - 48px));margin:14px auto 20px;padding:0;background:transparent;border:0;border-radius:0;box-shadow:none}
        .vl-live-search{position:relative}
        /* Exact Header.tsx .nav-search field treatment: no icon, no input box/radius,
           44px minimum row, transparent fill, 16px/400 type, one bottom hairline,
           green + lime focus underline. */
        .vl-live-search-field{display:block;min-height:44px;padding:0;background:transparent;border-radius:0}
        .vl-live-search-field input{width:100%;min-height:44px;box-sizing:border-box;border:0;border-bottom:1px solid #e5e7eb;border-radius:0;background:transparent;padding:0 2px;font-size:16px;font-weight:400;line-height:1.3;color:rgba(0,0,0,.898);font-family:inherit;outline:none;transition:border-color .2s,box-shadow .2s}
        .vl-live-search-field input::placeholder{color:rgba(0,0,0,.42)}
        .vl-live-search-field input::-webkit-search-cancel-button,.vl-live-search-field input::-webkit-search-decoration{display:none;-webkit-appearance:none}
        .vl-live-search-field input::-ms-clear{display:none;width:0;height:0}
        .vl-live-search-field input:focus-visible{border-bottom-color:#1a3a2a;box-shadow:0 1px 0 0 #d1f470}
        .vl-live-search-results{position:absolute;top:calc(100% + 8px);left:0;right:0;z-index:31;margin:0;padding:6px;list-style:none;border:1px solid var(--hair);border-radius:14px;background:#fff;box-shadow:0 10px 24px rgba(26,58,42,.14)}
        .vl-live-search-results li{padding:10px 12px;border-radius:10px;cursor:pointer}
        .vl-live-search-results li[aria-selected="true"]{background:var(--lime-tint)}
        .vl-live-search-results strong,.vl-live-search-results span{display:block}
        .vl-live-search-results strong{font-size:15px;font-weight:700;color:var(--heading)}
        .vl-live-search-results span{margin-top:3px;font-size:12px;color:var(--muted)}
        .vl-live-search-status{margin:8px 2px 0;font-size:11px;color:var(--muted)}
        @media(max-width:1050px){
          .vl-live-map-shell{height:auto;min-height:min(560px,66svh)}
        }
        @media(max-width:700px){
          .vl-live-shell{padding:0 max(10px,env(safe-area-inset-right)) max(44px,env(safe-area-inset-bottom)) max(10px,env(safe-area-inset-left))}
          .vl-live-map-shell{height:auto;min-height:min(460px,62svh);max-height:none}
          .vl-live-map-search{width:calc(100% - 20px);margin:10px auto 16px;padding:0}
          .vl-live-air-card-wrap{width:calc(100% - 20px - env(safe-area-inset-left) - env(safe-area-inset-right));margin:10px 0 112px max(10px,env(safe-area-inset-left))}
          .vl-live-air-card{padding:20px}
          .vl-live-air-context{align-items:flex-start}
          .vl-live-air-context-item.is-location{max-width:56%}
          .vl-live-air-context-item.is-time{margin-left:auto}
          .vl-live-air-health-tabs{scroll-snap-type:x mandatory;overscroll-behavior-x:contain;scroll-padding-inline:2px}
          .vl-live-air-history-head,.vl-live-air-forecast-head{align-items:flex-start;flex-direction:column}
          .vl-live-air-history-head-meta{width:100%;justify-content:space-between}
          .vl-live-air-range{max-width:100%;overflow-x:auto}
          .vl-live-air-health-tab{scroll-snap-align:start}
          .vl-live-air-gauge-row{gap:12px}
          .vl-live-wind-path.p6,.vl-live-wind-path.p7{display:none}
        }
        @media(max-height:500px) and (orientation:landscape){
          .vl-live-map-shell{height:auto;min-height:250px}
          .vl-live-search-field{min-height:44px}
        }
        @media(min-width:701px) and (max-width:900px) and (orientation:portrait){
          .vl-live-air-card-wrap{width:min(416px,48%)}
          .vl-live-map-search{width:min(760px,100%)}
        }
        @media(prefers-reduced-motion:reduce){
          .vl-live *{scroll-behavior:auto!important;transition:none!important}
          .vl-live-cloud-field,.vl-live-wind-path,.vl-live-vortex{animation:none!important}
        }
      `}</style>
    </section>
  );
};

export default VayuLokLive;