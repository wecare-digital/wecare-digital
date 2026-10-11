import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import BlogContribution from './BlogContribution';
import ShareLinks from './ShareLinks';
import { SUBSCRIBE_CTA_HREF } from '../content/subscribe';

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
 * DEFAULT-ON MAP TILE OVERLAYS. Two Google tile overlays paint by DEFAULT once the KEYED
 * map is initialized: (a) the continuous AQI air-quality heatmap (UAQI_RED_GREEN) and
 * (b) a weather/storm tile overlay. Each is INDEPENDENTLY toggleable from its own switch in
 * the Air panel, and each is attached only through the same keyed + map-ready guarded path
 * the rest of the map uses. On the KEYLESS path (no NEXT_PUBLIC_GOOGLE_MAPS_KEY, i.e. every
 * CI/sandbox run) NO ImageMapType is ever constructed and ZERO network calls fire - "default
 * on" strictly means "attached once a keyed map exists", never on the keyless placeholder.
 * The PM2.5 deck.gl dot overlay stays independent and is still only built when PM2.5 is
 * selected.
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

// WECARE.DIGITAL selected-place marker: dark green body, lime centre, white ring.
const BRAND_MARKER_ICON = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent( `<svg xmlns="http://www.w3.org/2000/svg" width="38" height="48" viewBox="0 0 38 48"><path fill="#1a3a2a" d="M19 0C8.5 0 0 8.5 0 19c0 14.3 19 29 19 29s19-14.7 19-29C38 8.5 29.5 0 19 0Z"/><circle cx="19" cy="19" r="7.5" fill="#fff"/><circle cx="19" cy="19" r="5" fill="#d1f470"/></svg>` )}`;

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

// Global map: do not re-introduce a lat/lng restriction here. Visitors can pan the
// live Google map anywhere and place search is intentionally worldwide.

// Place-autocomplete debounce. 120ms is a deliberately snappy value: it keeps ONE
// Autocomplete Data API request per settled keystroke (so a fast typist does not spam the
// SKU) while feeling immediate rather than the previous 300ms lag. The session-token reuse
// (autocompleteTokenRef) behavior is unchanged; only the settle delay is shorter.
const SEARCH_DEBOUNCE_MS = 120;

// The canonical, ABSOLUTE /vayulok/ page URL. ShareLinks requires an absolute URL (a share
// target handed a relative path shares nothing), and this page's furniture points at it.
const VAYULOK_PAGE_URL = 'https://wecare.digital/vayulok/';
const VAYULOK_SHARE_TITLE = 'VayuLok - live air quality across India';

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
const AQI_HEATMAP_TILE_BASE = 'https://airquality.googleapis.com/v1/mapTypes';

// Continuous WEATHER/STORM TILE overlay (the swirling cloud/radar "storm effect" from the
// reference). Google's weather/radar imagery is served through the Map Tiles API on
// tile.googleapis.com, whose tile GETs follow the {zoom}/{x}/{y} template shape:
//   https://tile.googleapis.com/v1/2dtiles/{zoom}/{x}/{y}?key=...
// IMPORTANT ENTITLEMENT CAVEAT: unlike the Air Quality heatmap (which is directly
// URL-templatable with just ?key=), the Map Tiles weather product normally requires a
// SESSION-TOKEN flow (POST createSession, then tiles with ?session=&key=) and is typically
// NOT entitled on a referrer-restricted BROWSER key. We attach it as a real second
// ImageMapType whose getTileUrl returns this documented tile shape (with the key, plus a
// session query param when one is available). If the key is unentitled or no session exists,
// the tile requests simply 403/404 and the ImageMapType paints NOTHING for those tiles - the
// overlay degrades SILENTLY with no broken image and no error UI, exactly like the rest of
// this component. We do NOT fabricate a synthetic storm layer. See the SCOPED RED EXCEPTION
// above: any red in these server-rendered tiles is confined to the tile IMAGES only.
const WEATHER_TILE_MAP_TYPE = 'weather';
const WEATHER_TILE_BASE = 'https://tile.googleapis.com/v1/2dtiles';

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
  // area the owner selected as the initial VayuLok destination. Search/map clicks can
  // still replace it immediately; live Weather/Air requests use these coordinates.
  name: 'Lumpyngngad',
  addr: 'Shillong, Meghalaya',
  lat: 25.5586,
  lng: 91.8985,
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
   Static, honest health guidance shown under the Air panel. These are generic air-quality
   advisories (NOT a live Google field), rendered only when `air` is present. Each line is
   kept short and crisp (one or two tight sentences) while staying honest. Each persona
   carries an id, an accessible label, a short recommendation, and an aria-hidden inline-SVG
   icon marker (Material-Symbols-equivalent paths, lime-tinted when active). Severity is
   never implied by colour here - the selected highlight is brand green/lime UI chrome. */
type HealthPersonaIcon = 'general' | 'elderly' | 'respiratory' | 'heart';
interface HealthPersona {
  id: string;
  label: string;
  recommendation: string;
  icon: HealthPersonaIcon;
}
const HEALTH_PERSONAS: HealthPersona[] = [
  {
    id: 'general',
    label: 'General population',
    recommendation: 'Air is fine for most people. Ease off outdoors if you feel unwell.',
    icon: 'general',
  },
  {
    id: 'elderly',
    label: 'Elderly',
    recommendation: 'Cut back on hard outdoor effort if you cough or feel short of breath. Keep away from traffic, smoke and dust.',
    icon: 'elderly',
  },
  {
    id: 'respiratory',
    label: 'Respiratory',
    recommendation: 'Keep your reliever inhaler handy and go easy outdoors. Head inside if you wheeze or feel tight-chested.',
    icon: 'respiratory',
  },
  {
    id: 'heart',
    label: 'Heart',
    recommendation: 'Pace yourself outdoors and rest if you feel chest discomfort or palpitations. Favour quieter routes away from traffic.',
    icon: 'heart',
  },
];

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
interface AirState {
  aqi: number;
  word: string;
  sev: Sev;
  dominant?: string;
  pollutants: { code: string; label: string; value: number; unit: string; sources?: string; effects?: string }[];
  advisory?: string;
  updatedAt?: string;
}
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

// HONEST SHARE TITLE. Composes the single string ShareLinks carries into the WhatsApp message
// first line and navigator.share { title, text }. It summarises the SELECTED PLACE's live air +
// weather for previewPlace, and degrades honestly: a clause only appears when its source data is
// actually in state. On the keyless/sandbox path air === null and weather === null, so this
// returns the place name alone (never a fabricated AQI/weather number); when even the place name
// is blank it falls back to the neutral VAYULOK_SHARE_TITLE. Every emitted number is read straight
// from state - no 'NaN', no 'undefined', no invented units.
export function composeVayuLokShareTitle(
  placeName: string | undefined | null,
  air: AirState | null,
  weather: WeatherState | null,
): string {
  const name = ( placeName || '' ).trim();
  if ( !name ) return VAYULOK_SHARE_TITLE;

  // Air clause: AQI <n> (<word>) with the dominant pollutant appended when present. aqi is a
  // finite number by the time AirState exists, but guard anyway so a malformed value is dropped
  // rather than rendered as 'AQI NaN'.
  let airClause = '';
  if ( air && Number.isFinite( air.aqi ) && air.word ) {
    airClause = `AQI ${ Math.round( air.aqi ) } (${ air.word })`;
    if ( air.dominant ) airClause += `, ${ air.dominant } dominant`;
  }

  // Weather clause: <temp>°C with the condition appended when present. temp is already rounded at
  // ingest; still guard for finiteness so an absent temp never prints 'undefined°C'.
  let weatherClause = '';
  if ( weather ) {
    const parts: string[] = [];
    if ( Number.isFinite( weather.temp ) ) parts.push( `${ Math.round( weather.temp as number ) }°C` );
    if ( weather.condition ) parts.push( weather.condition );
    weatherClause = parts.join( ', ' );
  }

  // Grammatical for every combination: place-only, place+air, place+weather, full.
  let summary: string;
  if ( airClause && weatherClause ) summary = `Air quality in ${ name }: ${ airClause } - ${ weatherClause }`;
  else if ( airClause ) summary = `Air quality in ${ name }: ${ airClause }`;
  else if ( weatherClause ) summary = `${ name }: ${ weatherClause }`;
  else summary = name;

  return `${ summary } | VayuLok`;
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
  const idx = indexes.find( ( i: any ) => i?.code === 'ind_cpcb' ) || indexes.find( ( i: any ) => i?.code === 'uaqi' ) || indexes[ 0 ];
  const aqi = n( idx?.aqi );
  if ( !Number.isFinite( aqi ) ) return null;
  const pm = ( Array.isArray( row?.pollutants ) ? row.pollutants : [] ).find( ( p: any ) => p?.code === 'pm25' );
  const pm25 = n( pm?.concentration?.value );
  return {
    time,
    aqi: Math.round( aqi ),
    word: typeof idx?.category === 'string' ? idx.category : aqiCategory( aqi ).word,
    ...( Number.isFinite( pm25 ) ? { pm25 } : {} ),
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

/* Parse a currentConditions:lookup payload into the LEFT-card AirState (AQI value +
   category word + severity + pollutant rows + advisory). Returns null when no finite AQI
   arrived, so a point that fails to parse is DROPPED, never fabricated. Shared by the
   layer-activation center-point fetch; the grid points reuse airPointFromApi instead. */
function airStateFromApiData( data: Record<string, any> | null | undefined ): AirState | null {
  const indexes: { code?: string; aqi?: number; dominantPollutant?: string }[] = data?.indexes || [];
  const idx = indexes.find( i => i.code === 'ind_cpcb' ) || indexes.find( i => i.code === 'uaqi' ) || indexes[ 0 ];
  if ( !idx || !Number.isFinite( idx.aqi ) ) return null;
  const aqi = idx.aqi as number;
  const cat = aqiCategory( aqi );
  const pollutants: AirState['pollutants'] = [];
  ( data?.pollutants || [] ).forEach( ( p: { code?: string; concentration?: { value?: number; units?: string }; additionalInfo?: { sources?: string; effects?: string } } ) => {
    const label = p.code ? POLLUTANT_LABELS[ p.code ] : undefined;
    const v = p.concentration?.value;
    if ( label && Number.isFinite( v ) ) {
      pollutants.push( {
        code: p.code as string,
        label,
        value: v as number,
        unit: concUnitLabel( p.concentration?.units ),
        // Carry Google's per-pollutant sources/effects ONLY when present as a non-empty
        // string; absent additionalInfo leaves the field undefined (never fabricated).
        ...( typeof p.additionalInfo?.sources === 'string' && p.additionalInfo.sources ? { sources: p.additionalInfo.sources } : {} ),
        ...( typeof p.additionalInfo?.effects === 'string' && p.additionalInfo.effects ? { effects: p.additionalInfo.effects } : {} ),
      } );
    }
  } );
  const advisory = data?.healthRecommendations?.generalPopulation;
  return {
    aqi,
    word: cat.word,
    sev: cat.sev,
    dominant: idx.dominantPollutant || undefined,
    pollutants,
    advisory: typeof advisory === 'string' ? advisory : undefined,
    updatedAt: typeof data?.dateTime === 'string' ? data.dateTime : undefined,
  };
}

/* The request body shared by the center-point and grid air fetches - identical shape to
   the former single-point fetchAir so dots carry the same real currentConditions values. */
function airRequestBody( lat: number, lng: number ): Record<string, unknown> {
  return {
    location: { latitude: lat, longitude: lng },
    extraComputations: [
      'POLLUTANT_CONCENTRATION',
      'LOCAL_AQI',
      'HEALTH_RECOMMENDATIONS',
      'DOMINANT_POLLUTANT_CONCENTRATION',
    ],
    languageCode: 'en',
    universalAqi: true,
    // Parity with fetchAir + loadAirForecast + the air-history call: request the India CPCB
    // local AQI so airStateFromApiData (which prefers ind_cpcb) can receive it here too.
    customLocalAqis: [ { regionCode: 'IN', aqi: 'ind_cpcb' } ],
  };
}

/* A sampled dot: a REAL grid point carrying its lat/lng and parsed AQI/PM2.5. */
interface AirDot {
  lat: number;
  lng: number;
  aqi: number;
  pm25?: number;
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
  // are useful on first paint; search and map clicks continue to replace this selection.
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
  const [ layer, setLayer ] = useState<'AQI' | 'PM25' | null>( 'AQI' );

  // Weather/storm TILE overlay on/off, INDEPENDENT of `layer` so it coexists with AQI or
  // PM2.5. Defaults ON so the storm effect paints by DEFAULT on the keyed map; the keyed +
  // map-ready guard still gates attachment so the keyless path creates NOTHING. Its switch
  // turns it OFF.
  const [ stormOn, setStormOn ] = useState( true );

  // Health Recommendations: which persona's advisory is shown under the Air panel. Defaults
  // to the Elderly persona (index 1) per the reference design. Pure UI state - no fetch.
  const [ healthPersona, setHealthPersona ] = useState( 1 );
  // Hourly History: window offset for the prev/next chart navigation. 0 = latest week; a
  // positive value scrolls further back through the loaded airHistory points. Pure UI state.
  const [ historyOffset, setHistoryOffset ] = useState( 0 );

  const mapHost = useRef<HTMLDivElement | null>( null );
  const mapRef = useRef<unknown>( null );
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
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>( null );
  // FEAT-002: the deck.gl GoogleMapsOverlay instance (created lazily on first layer
  // activation), the AbortController for the in-flight grid fetch, and the grid cache
  // keyed by area+grid+layer+time-bucket so re-activating the same layer bills nothing.
  const deckOverlayRef = useRef<unknown>( null );
  // The google.maps.ImageMapType instance for the continuous AQI heatmap tile overlay
  // (FEAT-001). Attached by DEFAULT once the KEYED map is initialized (layer defaults to
  // 'AQI'), pushed onto map.overlayMapTypes, and detached idempotently on toggle-off /
  // switch-to-PM2.5 / unmount. On the keyless path it is NEVER constructed.
  const heatmapOverlayRef = useRef<unknown>( null );
  // The google.maps.ImageMapType instance for the weather/storm tile overlay (FEAT-001).
  // Attached by DEFAULT once the KEYED map is initialized (stormOn defaults to true), pushed
  // onto map.overlayMapTypes alongside the AQI heatmap, and detached idempotently on
  // toggle-off / unmount. On the keyless path it is NEVER constructed; unentitled tiles 403/404
  // and paint nothing (silent degradation).
  const weatherOverlayRef = useRef<unknown>( null );
  const gridAbortRef = useRef<AbortController | null>( null );
  const gridCache = useRef<Record<string, { ts: number; dots: AirDot[]; center: AirState | null }>>( {} );

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
        center: { lat: 20, lng: 20 },
        zoom: 2,
        mapTypeId: 'hybrid',
        gestureHandling: 'greedy',
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

      // No selected-place marker exists on load. Keep the constructor and create the
      // branded marker lazily after the first real selection.
      markerCtorRef.current = maps.Marker || null;

      if ( maps.Geocoder ) geocoder.current = new maps.Geocoder();
      placesLibRef.current = placesLib || maps.places || null;

      const interactiveMap = map as {
        addListener?: ( eventName: string, handler: ( event?: any ) => void ) => { remove?: () => void };
      };
      interactiveMap.addListener?.( 'click', ( event?: any ) => {
        const lat = event?.latLng?.lat?.();
        const lng = event?.latLng?.lng?.();
        if ( !Number.isFinite( lat ) || !Number.isFinite( lng ) ) return;
        const gc = geocoder.current as {
          geocode?: ( req: Record<string, unknown>, cb: ( rows: unknown[] | null, status: string ) => void ) => void;
        } | null;
        gc?.geocode?.( { location: { lat, lng }, extraComputations: [ 'ADDRESS_DESCRIPTORS' ] }, async ( rows, status ) => {
          if ( status !== 'OK' || !Array.isArray( rows ) || !rows.length ) return;
          const first = rows[ 0 ] as { formatted_address?: string; place_id?: string } | undefined;
          if ( !first ) return;
          const next: PlaceState = {
            name: first.formatted_address?.split( ',' )[ 0 ] || 'Selected location',
            addr: first.formatted_address || '',
            lat,
            lng,
            placeId: first.place_id,
          };
          setHasSelection( true );
          setSearchStatus( 'idle' );
          // 03C - selecting an area (here via a map click) recenters the map on that
          // area's geocoded lat/lng and loads its live data, exactly like choosing a
          // search result. The recenter effect (center + zoom 14 + marker move) fires on
          // the place change, so only the selected area's geocoding is shown. mapCandidate
          // continues to drive the on-map metadata enrichment below.
          setMapCandidate( next );
          setPlace( next );

          // If reverse geocoding produced a Place ID, enrich the preview with the honest
          // Google Place metadata the on-map selected label can show (primary type,
          // viewport, rating, etc.). We do NOT request Places photos: the floating card
          // renders no photo rail, so fetching them would be a wasted Places request.
          if ( first.place_id ) {
            const lib = placesLibRef.current as {
              Place?: new ( opts: { id: string } ) => GooglePlaceLike;
            } | null;
            const PlaceCtor = lib?.Place;
            if ( PlaceCtor ) {
              try {
                const googlePlace = new PlaceCtor( { id: first.place_id } );
                await googlePlace.fetchFields?.( { fields: [ ...PLACE_META_FIELDS ] } );
                const meta = metaFromGooglePlace( googlePlace );
                if ( Object.keys( meta ).length ) {
                  setMapCandidate( current => current && current.lat === lat && current.lng === lng
                    ? { ...current, ...meta }
                    : current );
                  setPlace( current => current.lat === lat && current.lng === lng
                    ? { ...current, ...meta }
                    : current );
                }
              } catch { /* metadata enrichment is optional */ }
            }
          }
        } );
      } );

      // A constructed Map is not the same thing as a painted map. With an invalid or
      // refused browser key Google can still create the map object while its tiles never
      // arrive, which previously hid the fallback and exposed a blank panel. Only reveal
      // the Maps JS canvas after the first visible tile batch has loaded.
      const mapWithEvents = map as {
        addListener?: ( eventName: string, handler: () => void ) => { remove?: () => void };
      };
      if ( typeof mapWithEvents.addListener === 'function' ) {
        let painted = false;
        mapWithEvents.addListener( 'tilesloaded', () => {
          if ( painted || cancelled ) return;
          painted = true;
          requestAnimationFrame( () => {
            if ( !cancelled ) setMapReady( true );
          } );
        } );
      } else {
        // Legacy/test doubles without Maps event support: preserve the old behavior.
        requestAnimationFrame( () => {
          if ( !cancelled ) setMapReady( true );
        } );
      }
    };

    // init is async (it awaits importLibrary); wrap so no unhandled promise floats.
    const runInit = () => { void init(); };

    // Do not use the script element's 'load' event as the readiness signal.
    // With Google's loading=async mode, API readiness is intentionally decoupled
    // from that event. runInit() waits for google.maps and then importLibrary().
    if ( w.google?.maps ) { runInit(); return () => { cancelled = true; }; }

    const ID = 'gmaps-js';
    const existing = document.getElementById( ID );
    if ( existing ) {
      runInit();
      return () => { cancelled = true; };
    }

    const script = document.createElement( 'script' );
    script.id = ID;
    script.async = true;
    // Places library requested so client-side India-scoped autocomplete can run.
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent( MAPS_KEY )}&libraries=places&loading=async&v=beta`;
    document.head.appendChild( script );
    // Start the same namespace-readiness path immediately; it will resolve once
    // the async loader exposes google.maps, without depending on a DOM load event.
    runInit();
    return () => { cancelled = true; };
  }, [] );

  /* ---------------------------------------------------------------------------------
     LAYER-ACTIVATION DATA (FEAT-002). Selecting a place restores the compact weather/forecast experience on the LEFT.
     The spatial AQI/PM2.5 dot grid remains user-triggered by the layer pills, so selecting
     a place alone never fans out the 3x3/5x5 air sampling requests.

     This one effect: (1) fetches the grid's CENTER currentConditions and reuses it both as
     the left-card `air` state AND as the grid's center cell (no double-fetch); (2) fans the
     rest of the responsive, capped grid out through a <=4-in-flight throttle; (3) parses
     every point with the existing helpers, dropping unparseable points; (4) caches by
     area+grid+layer+time-bucket in a ref (+localStorage mirror); (5) builds a deck.gl
     ScatterplotLayer and attaches a dynamically-imported GoogleMapsOverlay to the map; and
     (6) on deactivate/unmount clears the overlay and aborts any in-flight grid fetch.

     FEAT-001: the AQI layer no longer uses the deck.gl dot grid. When layer === 'AQI' it
     paints a CONTINUOUS Google Air Quality heatmap TILE overlay (a google.maps.ImageMapType
     pushed onto map.overlayMapTypes) instead, and that layer defaults ON so the heatmap
     paints by DEFAULT once the keyed map is ready. The weather/storm TILE overlay is driven
     by the INDEPENDENT `stormOn` state (default ON) in a sibling effect below. The PM2.5
     layer keeps its no-red deck.gl dots unchanged. Only one AQI-vs-PM2.5 overlay is attached
     at a time; the weather overlay coexists with whichever is active. Every attachment stays
     behind the keyed + map-ready guard, so the keyless path constructs NOTHING. */
  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;

    const map = mapRef.current;

    // Detach the deck.gl dot overlay (used by the PM2.5 layer) idempotently.
    const detachDots = () => {
      const existing = deckOverlayRef.current as { setMap?: ( m: unknown ) => void; setProps?: ( p: { layers: unknown[] } ) => void } | null;
      existing?.setProps?.( { layers: [] } );
      existing?.setMap?.( null );
    };

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

    // No layer active -> ensure BOTH overlay types are detached and the single-point air clears.
    if ( !layer ) {
      detachDots();
      detachHeatmap();
      requestAnimationFrame( () => { setDataLoading( false ); } );
      return;
    }
    if ( !map ) return;

    // AQI -> continuous heatmap TILE overlay (no deck.gl dot grid, no grid fetch). Tear down
    // the PM2.5 dots first so the two overlay types are never shown at once, then attach the
    // ImageMapType exactly once. Attached by DEFAULT here (layer defaults to 'AQI') once the
    // keyed map is ready - never at module load, never on the keyless path.
    if ( layer === 'AQI' ) {
      detachDots();
      const w = window as unknown as { google?: { maps?: {
        ImageMapType?: new ( opts: Record<string, unknown> ) => unknown;
        Size?: new ( w: number, h: number ) => unknown;
      } } };
      const gmaps = w.google?.maps;
      const omt = ( map as { overlayMapTypes?: { push?: ( v: unknown ) => void } } ).overlayMapTypes;
      // Idempotent: if one is already attached, leave it; never push a duplicate.
      if ( gmaps?.ImageMapType && gmaps?.Size && omt?.push && !heatmapOverlayRef.current ) {
        const imageMapType = new gmaps.ImageMapType( {
          name: 'vl-live-aqi-heatmap',
          tileSize: new gmaps.Size( 256, 256 ),
          minZoom: 0,
          maxZoom: 16,
          opacity: 0.9, // denser pollution cloud; base map/pin/attribution stay legible
          // SCOPED RED EXCEPTION (see AQI_HEATMAP_MAP_TYPE above): these server-rendered
          // tiles may contain red for high pollution and that is deliberately allowed for
          // the tile IMAGES only. No component CSS/markup introduces red.
          getTileUrl: ( coord: { x: number; y: number }, zoom: number ): string =>
            `${AQI_HEATMAP_TILE_BASE}/${AQI_HEATMAP_MAP_TYPE}/heatmapTiles/${zoom}/${coord.x}/${coord.y}`
            + `?key=${encodeURIComponent( MAPS_KEY )}`,
        } );
        omt.push( imageMapType );
        heatmapOverlayRef.current = imageMapType;
      }
      requestAnimationFrame( () => { setDataLoading( false ); } );
      return () => { detachHeatmap(); };
    }

    // PM2.5 -> keep the existing no-red deck.gl ScatterplotLayer dot grid unchanged. Tear down
    // any AQI heatmap tiles first so both overlay types are never shown at once.
    detachHeatmap();

    const { lat, lng } = place;
    const gridSize = typeof window !== 'undefined' && window.innerWidth < 640 ? 3 : 5; // 3x3 narrow, 5x5 wide
    const timeBucket = Math.floor( Date.now() / ( 10 * 60 * 1000 ) ); // ~10 min cache bucket
    const gridKey = `${lat.toFixed( 3 )},${lng.toFixed( 3 )}|${gridSize}|${layer}|${timeBucket}`;

    const ac = new AbortController();
    gridAbortRef.current = ac;
    setDataLoading( true );
    setCoreError( false );

    // Build the responsive, hard-capped (<=25) grid of lat/lng offsets around the place.
    // A ~+/-0.04deg span keeps the dots local around the zoom-14 marker.
    const SPAN = 0.04;
    const half = ( gridSize - 1 ) / 2;
    const centerIdx = Math.floor( ( gridSize * gridSize ) / 2 );
    const cells: { lat: number; lng: number }[] = [];
    for ( let r = 0; r < gridSize; r++ ) {
      for ( let c = 0; c < gridSize; c++ ) {
        cells.push( {
          lat: lat + ( ( r - half ) / Math.max( 1, half ) ) * SPAN,
          lng: lng + ( ( c - half ) / Math.max( 1, half ) ) * SPAN,
        } );
      }
    }
    const cappedCells = cells.slice( 0, 25 );

    const fetchPoint = async ( cell: { lat: number; lng: number } ): Promise<{ data: Record<string, any> | null }> => {
      try {
        const res = await fetch(
          `https://airquality.googleapis.com/v1/currentConditions:lookup?key=${encodeURIComponent( MAPS_KEY )}`,
          {
            method: 'POST',
            signal: ac.signal,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify( airRequestBody( cell.lat, cell.lng ) ),
          },
        );
        if ( !res.ok ) return { data: null };
        return { data: await res.json() };
      } catch { return { data: null }; }
    };

    // Throttle to <=4 concurrent requests. The center cell is fetched first so its
    // currentConditions can populate the left-card `air` as soon as it lands.
    const runThrottled = async (): Promise<{ dots: AirDot[]; center: AirState | null }> => {
      const dots: AirDot[] = [];
      let center: AirState | null = null;
      // Raw response of the FIRST grid cell that parsed into a dot, kept so the left-card
      // reading can fall back to it when the center cell itself fails to parse (review
      // issue #1). We reuse a cell we already fetched - never an extra request.
      let fallbackData: Record<string, any> | null = null;
      let cursor = 0;
      const CONCURRENCY = 4;
      const worker = async () => {
        while ( cursor < cappedCells.length && !ac.signal.aborted ) {
          const i = cursor++;
          const cell = cappedCells[ i ];
          const { data } = await fetchPoint( cell );
          if ( ac.signal.aborted || !data ) continue;
          // Reuse the EXISTING airPointFromApi parser for each grid point. For the center
          // cell, also build the richer AirState for the left-card result (no double-fetch).
          const point = airPointFromApi( data );
          if ( point ) {
            const dot: AirDot = { lat: cell.lat, lng: cell.lng, aqi: point.aqi };
            if ( Number.isFinite( point.pm25 ) ) dot.pm25 = point.pm25;
            dots.push( dot );
            // Remember the first dot-producing cell's raw payload for the fallback below.
            if ( !fallbackData ) fallbackData = data;
          }
          if ( i === centerIdx ) {
            const parsed = airStateFromApiData( data );
            if ( parsed ) {
              center = parsed;
              requestAnimationFrame( () => { if ( !ac.signal.aborted ) setAir( parsed ); } );
            }
          }
        }
      };
      await Promise.all( Array.from( { length: Math.min( CONCURRENCY, cappedCells.length ) }, () => worker() ) );
      // Center-cell preferred, but if it did not parse, derive the left-card reading from
      // the first successfully-parsed grid cell's raw response (reusing airStateFromApiData
      // on data we already fetched). This keeps a real reading showing whenever ANY cell
      // parsed - real values only, nothing fabricated.
      if ( center === null && fallbackData ) {
        const fallbackCenter = airStateFromApiData( fallbackData );
        if ( fallbackCenter ) {
          center = fallbackCenter;
          requestAnimationFrame( () => { if ( !ac.signal.aborted ) setAir( fallbackCenter ); } );
        }
      }
      return { dots, center };
    };

    // Build the deck.gl ScatterplotLayer from parsed dots and push it onto the overlay. The
    // deck.gl modules are imported DYNAMICALLY here so SSR/the initial bundle and the
    // honest-degradation path (no key -> this effect early-returns) never load them.
    const render = async ( dots: AirDot[] ) => {
      if ( ac.signal.aborted || !dots.length ) return;
      try {
        const [ { GoogleMapsOverlay }, { ScatterplotLayer } ] = await Promise.all( [
          import( '@deck.gl/google-maps' ),
          import( '@deck.gl/layers' ),
        ] );
        if ( ac.signal.aborted ) return;
        if ( !deckOverlayRef.current ) {
          deckOverlayRef.current = new GoogleMapsOverlay( { interleaved: false } );
        }
        const overlay = deckOverlayRef.current as {
          setMap: ( m: unknown ) => void;
          setProps: ( p: { layers: unknown[] } ) => void;
        };
        const scatter = new ScatterplotLayer( {
          id: `vl-live-air-dots-${layer}`,
          data: dots,
          pickable: false,
          stroked: true,
          filled: true,
          radiusUnits: 'pixels',
          getPosition: ( d: AirDot ) => [ d.lng, d.lat ],
          getRadius: 9,
          lineWidthUnits: 'pixels',
          getLineWidth: 1.5,
          getLineColor: DOT_LINE_RGBA,
          getFillColor: ( d: AirDot ): [ number, number, number, number ] => {
            const sev: Sev = layer === 'PM25' && Number.isFinite( d.pm25 )
              ? pm25Severity( d.pm25 as number )
              : aqiCategory( d.aqi ).sev;
            return DOT_FILL_RGBA[ sev ];
          },
        } );
        overlay.setProps( { layers: [ scatter ] } );
        overlay.setMap( map );
      } catch { /* deck.gl unavailable -> degrade silently, map still renders */ }
    };

    ( async () => {
      let dots: AirDot[] | null = null;
      let center: AirState | null = null;
      // 1) Cache hit within the time bucket bills nothing.
      const cached = gridCache.current[ gridKey ];
      if ( cached ) {
        dots = cached.dots;
        center = cached.center;
      } else {
        // 1b) localStorage mirror for cross-reload reuse (guarded, silent on failure).
        try {
          const raw = window.localStorage?.getItem( `vl-live-grid:${gridKey}` );
          if ( raw ) {
            const parsed = JSON.parse( raw ) as { dots: AirDot[]; center: AirState | null };
            if ( Array.isArray( parsed?.dots ) ) { dots = parsed.dots; center = parsed.center ?? null; }
          }
        } catch { /* storage unavailable */ }
      }

      if ( dots ) {
        if ( center ) requestAnimationFrame( () => { if ( !ac.signal.aborted ) setAir( center ); } );
        await render( dots );
        requestAnimationFrame( () => { if ( !ac.signal.aborted ) setDataLoading( false ); } );
        return;
      }

      const result = await runThrottled();
      if ( ac.signal.aborted ) return;
      dots = result.dots;
      center = result.center;
      gridCache.current[ gridKey ] = { ts: Date.now(), dots, center };
      try {
        window.localStorage?.setItem( `vl-live-grid:${gridKey}`, JSON.stringify( { dots, center } ) );
      } catch { /* storage unavailable */ }
      await render( dots );
      requestAnimationFrame( () => {
        if ( ac.signal.aborted ) return;
        // coreError is about the LEFT-card reading, not the dots: surface the retry only
        // when NO usable reading could be derived (no center AND no first-cell fallback),
        // regardless of how many dots rendered (review issue #1).
        setCoreError( center === null );
        setDataLoading( false );
      } );
    } )();

    return () => {
      ac.abort();
      const overlay = deckOverlayRef.current as { setProps?: ( p: { layers: unknown[] } ) => void; setMap?: ( m: unknown ) => void } | null;
      overlay?.setProps?.( { layers: [] } );
      overlay?.setMap?.( null );
    };
  }, [ layer, place, refreshNonce, mapReady, hasSelection ] );

  /* ---------------------------------------------------------------------------------
     WEATHER/STORM TILE OVERLAY (FEAT-001). Driven by the INDEPENDENT `stormOn` state so it
     coexists with whichever AQI/PM2.5 layer is active. Attached by DEFAULT (stormOn starts
     true) once the KEYED map is ready, behind the SAME keyed + map-ready guard as every other
     map effect, so the keyless path constructs NO ImageMapType and fires zero network calls.
     Unentitled/sessionless weather tiles 403/404 and paint nothing (silent degradation). */
  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;

    const map = mapRef.current;

    // Detach the weather ImageMapType from map.overlayMapTypes idempotently, mirroring
    // detachHeatmap: remove this exact instance by index so the AQI heatmap and any other
    // overlay are untouched, then null the ref so a later toggle-on re-pushes exactly one.
    const detachWeather = () => {
      const overlay = weatherOverlayRef.current;
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
          // Minimal test double exposes only clear(). We only reach here when a weather
          // overlay was pushed, so clearing is acceptable in that stub environment.
          omt.clear?.();
        }
      }
      weatherOverlayRef.current = null;
    };

    if ( !stormOn ) { detachWeather(); return; }
    if ( !map ) return;

    const w = window as unknown as { google?: { maps?: {
      ImageMapType?: new ( opts: Record<string, unknown> ) => unknown;
      Size?: new ( w: number, h: number ) => unknown;
    } } };
    const gmaps = w.google?.maps;
    const omt = ( map as { overlayMapTypes?: { push?: ( v: unknown ) => void } } ).overlayMapTypes;
    // Idempotent: if one is already attached, leave it; never push a duplicate.
    if ( gmaps?.ImageMapType && gmaps?.Size && omt?.push && !weatherOverlayRef.current ) {
      const imageMapType = new gmaps.ImageMapType( {
        name: 'vl-live-weather-storm',
        tileSize: new gmaps.Size( 256, 256 ),
        minZoom: 0,
        maxZoom: 16,
        opacity: 0.6, // translucent cloud/radar so the AQI heatmap + base map stay readable
        // SCOPED RED EXCEPTION (see WEATHER_TILE_BASE above): these server-rendered weather
        // tiles may contain red; that red lives ONLY inside the tile IMAGES. No component
        // CSS/markup introduces red. An unentitled/sessionless tile 403/404s and paints
        // nothing, so the overlay degrades silently.
        getTileUrl: ( coord: { x: number; y: number }, zoom: number ): string =>
          `${WEATHER_TILE_BASE}/${WEATHER_TILE_MAP_TYPE}/${zoom}/${coord.x}/${coord.y}`
          + `?key=${encodeURIComponent( MAPS_KEY )}`,
      } );
      omt.push( imageMapType );
      weatherOverlayRef.current = imageMapType;
    }
    return () => { detachWeather(); };
  }, [ stormOn, place, refreshNonce, mapReady, hasSelection ] );

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
              // Request the India CPCB local AQI index so the parser below (which prefers
              // indexes.find( i => i.code === 'ind_cpcb' )) can actually receive it instead of
              // silently falling back to uaqi. Parity with loadAirForecast + the air-history
              // call, which already send this.
              customLocalAqis: [ { regionCode: 'IN', aqi: 'ind_cpcb' } ],
            } ),
          },
        );
        if ( !res.ok ) return;
        const data = await res.json();
        const indexes: { code?: string; aqi?: number; dominantPollutant?: string }[] = data?.indexes || [];
        // Prefer the India CPCB local AQI when present, else the universal AQI.
        const idx = indexes.find( i => i.code === 'ind_cpcb' ) || indexes.find( i => i.code === 'uaqi' ) || indexes[ 0 ];
        if ( !idx || !Number.isFinite( idx.aqi ) ) return;
        const aqi = idx.aqi as number;
        const cat = aqiCategory( aqi );
        const pollutants: AirState['pollutants'] = [];
        ( data?.pollutants || [] ).forEach( ( p: { code?: string; concentration?: { value?: number; units?: string }; additionalInfo?: { sources?: string; effects?: string } } ) => {
          const label = p.code ? POLLUTANT_LABELS[ p.code ] : undefined;
          const v = p.concentration?.value;
          if ( label && Number.isFinite( v ) ) {
            pollutants.push( {
              code: p.code as string,
              label,
              value: v as number,
              unit: concUnitLabel( p.concentration?.units ),
              // Carry Google's per-pollutant sources/effects ONLY when present as a non-empty
              // string; absent additionalInfo leaves the field undefined (never fabricated).
              ...( typeof p.additionalInfo?.sources === 'string' && p.additionalInfo.sources ? { sources: p.additionalInfo.sources } : {} ),
              ...( typeof p.additionalInfo?.effects === 'string' && p.additionalInfo.effects ? { effects: p.additionalInfo.effects } : {} ),
            } );
          }
        } );
        const advisory = data?.healthRecommendations?.generalPopulation;
        store.air = {
          aqi,
          word: cat.word,
          sev: cat.sev,
          dominant: idx.dominantPollutant || undefined,
          pollutants,
          advisory: typeof advisory === 'string' ? advisory : undefined,
          updatedAt: typeof data?.dateTime === 'string' ? data.dateTime : undefined,
        };
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
            customLocalAqis: [ { regionCode: 'IN', aqi: 'ind_cpcb' } ],
            extraComputations: [ 'LOCAL_AQI', 'POLLUTANT_CONCENTRATION', 'DOMINANT_POLLUTANT_CONCENTRATION' ],
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
          customLocalAqis: [ { regionCode: 'IN', aqi: 'ind_cpcb' } ],
          extraComputations: [ 'LOCAL_AQI', 'POLLUTANT_CONCENTRATION' ],
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
      // Branded selected-place marker. Created lazily after the first valid selection.
      markerRef.current = new MarkerCtor( {
        position: { lat: place.lat, lng: place.lng },
        map,
        title: place.name,
        icon: BRAND_MARKER_ICON,
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
    return () => { cancelled = true; };
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
        setResults( mapped );
        setActive( mapped.length ? 0 : -1 );
        setOpen( true );
        setSearchStatus( mapped.length ? 'idle' : 'no-results' );
        return;
      } catch {
        autocompleteTokenRef.current = null;
      }
    }

    // Fallback for a partial Maps load: Geocoding is worldwide. The Geocoder
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
            const place: PlaceState = {
              name: pr.formatted_address?.split( ',' )[ 0 ] || 'Place',
              addr: pr.formatted_address || '',
              lat: lat as number,
              lng: lng as number,
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
    // 03C - a fresh search selection owns the view: clear any lingering map-click
    // candidate so previewPlace (mapCandidate || place) and the on-map label follow the
    // newly chosen area, never a stale clicked location.
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
  // Honest, data-driven Share title for the selected place. On the keyless path (air/weather
  // null) this is just the place name (or the neutral VayuLok fallback) with no fabricated
  // numbers; it becomes the WhatsApp message first line and the navigator.share text.
  const shareTitle = useMemo(
    () => composeVayuLokShareTitle( previewPlace.name, air, weather ),
    [ previewPlace.name, air, weather ],
  );
  const currentPm25 = air?.pollutants.find( p => p.code === 'pm25' ) || null;
  const mapActive = Boolean( MAPS_KEY );
  const liveActive = Boolean( MAPS_KEY && hasSelection );

  return (
    <section className="vl-live" aria-label="VayuLok conditions">
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
              <aside className="vl-live-air-card" aria-label="Air quality details">
                <div className="vl-live-air-card-head">
                  <h3 className="vl-live-air-card-title">Air Quality Details</h3>
                </div>
                <hr className="vl-live-air-card-rule" aria-hidden="true" />

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
                        <div className={ `vl-live-air-gauge vl-live-air-sev-${air.sev}` }>
                          { ( () => {
                            // SVG ring gauge. The sweep encodes the AQI within the no-red ramp
                            // (dark green -> lime -> amber -> terracotta) mapped from air.sev;
                            // the number + category WORD carry severity so it never relies on
                            // colour alone (WCAG 1.4.1). AQI is clamped to a 0-500 scale sweep.
                            const r = 52;
                            const c = 2 * Math.PI * r;
                            const frac = Math.max( 0, Math.min( 1, air.aqi / 500 ) );
                            const dash = `${( frac * c ).toFixed( 1 )} ${c.toFixed( 1 )}`;
                            return (
                              <svg viewBox="0 0 120 120" className="vl-live-air-gauge-svg" role="img" aria-label={ `Universal AQI ${Math.round( air.aqi )}, ${air.word}` }>
                                <circle className="vl-live-air-gauge-track" cx="60" cy="60" r={ r } />
                                <circle
                                  className="vl-live-air-gauge-arc"
                                  cx="60" cy="60" r={ r }
                                  strokeDasharray={ dash }
                                  transform="rotate(-90 60 60)"
                                />
                              </svg>
                            );
                          } )() }
                          <span className="vl-live-air-gauge-value" aria-hidden="true">{ Math.round( air.aqi ) }</span>
                        </div>
                        <div className="vl-live-air-gauge-meta">
                          <strong className="vl-live-air-gauge-word">{ air.word } air quality</strong>
                          { air.dominant && (
                            <span className="vl-live-air-dominant">Dominant pollutant: { dominantPollutantLabel( air.dominant, air.pollutants ) }</span>
                          ) }
                        </div>
                      </div>

                      { air.pollutants.length > 0 && (
                        <div className="vl-live-air-pollutants">
                          <h4 className="vl-live-air-pollutants-title">Air Quality Details</h4>
                          <ul className="vl-live-air-pollutant-list">
                            { air.pollutants.map( p => (
                              <li className="vl-live-air-pollutant-row" key={ p.code }>
                                <span className="vl-live-air-pollutant-value">{ Math.round( p.value ) } <small>{ p.unit }</small></span>
                                <span className="vl-live-air-pollutant-label">{ p.label }</span>
                                <span
                                  className="vl-live-air-pollutant-info"
                                  role="button"
                                  tabIndex={ 0 }
                                  aria-label={ `${p.label} details` }
                                  aria-describedby={ `vl-live-air-pollutant-tip-${p.code}` }
                                >
                                  <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.5" /><line x1="10" y1="9" x2="10" y2="14" /><circle cx="10" cy="6" r=".9" /></svg>
                                  <span className="vl-live-air-pollutant-tip" id={ `vl-live-air-pollutant-tip-${p.code}` } role="tooltip">
                                    <span className="vl-live-air-pollutant-pop">
                                      <span className="vl-live-air-pollutant-pop-title">{ p.label }</span>
                                      { ( p.sources || p.effects ) ? (
                                        <>
                                          { p.sources && (
                                            <>
                                              <span className="vl-live-air-pollutant-pop-head">Sources:</span>
                                              <span className="vl-live-air-pollutant-pop-text">{ p.sources }</span>
                                            </>
                                          ) }
                                          { p.effects && (
                                            <>
                                              <span className="vl-live-air-pollutant-pop-head">Effects:</span>
                                              <span className="vl-live-air-pollutant-pop-text">{ p.effects }</span>
                                            </>
                                          ) }
                                        </>
                                      ) : (
                                        <span className="vl-live-air-pollutant-pop-text">{ `${p.label}: ${Math.round( p.value )} ${p.unit}` }</span>
                                      ) }
                                    </span>
                                  </span>
                                </span>
                              </li>
                            ) ) }
                          </ul>
                        </div>
                      ) }

                      {/* SECTION 1 - HEATMAP + STORM. Two label rows, each with an accessible
                          on/off switch. The Heatmap switch drives the `layer` state (the
                          continuous AQI heatmap TILE overlay, default ON); the Storm switch
                          drives the independent `stormOn` state (the weather/storm TILE
                          overlay, default ON). Neither issues a fetch here - the keyed +
                          map-ready guarded effects attach/detach the overlays. Both are
                          disabled until a place is selected, mirroring the .vl-live-layers
                          buttons. Below, a Poor -> Excellent legend bar on the approved no-red
                          ramp; the words (not the colour) carry the meaning (WCAG 1.4.1). */}
                      <div className="vl-live-air-heatmap">
                        <div className="vl-live-air-heatmap-row">
                          <span className="vl-live-air-heatmap-label">Heatmap</span>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={ layer === 'AQI' }
                            aria-label="Air quality heatmap"
                            disabled={ !hasSelection }
                            className={ `vl-live-air-heatmap-switch ${layer === 'AQI' ? 'is-on' : ''}`.trim() }
                            onClick={ () => setLayer( v => v === 'AQI' ? null : 'AQI' ) }
                          >
                            <span className="vl-live-air-heatmap-knob" aria-hidden="true" />
                          </button>
                        </div>
                        <div className="vl-live-air-heatmap-row">
                          <span className="vl-live-air-heatmap-label">Storm</span>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={ stormOn }
                            aria-label="Weather storm overlay"
                            disabled={ !hasSelection }
                            className={ `vl-live-air-heatmap-switch ${stormOn ? 'is-on' : ''}`.trim() }
                            onClick={ () => setStormOn( v => !v ) }
                          >
                            <span className="vl-live-air-heatmap-knob" aria-hidden="true" />
                          </button>
                        </div>
                        <div className="vl-live-air-heatmap-legend">
                          <span className="vl-live-air-heatmap-ramp" aria-hidden="true" />
                          <span className="vl-live-air-heatmap-ends">
                            <span className="vl-live-air-heatmap-end">Poor</span>
                            <span className="vl-live-air-heatmap-end">Excellent</span>
                          </span>
                        </div>
                      </div>

                      {/* SECTION 2 - HEALTH RECOMMENDATIONS. A role=tablist of persona icon
                          buttons (plus a '>' advance control), with exactly one selected
                          persona driving the recommendation paragraph below the divider. The
                          selected highlight is brand green/lime UI chrome, never a severity
                          colour; icons are aria-hidden and each button has an accessible name. */}
                      <div className="vl-live-air-health">
                        <h4 className="vl-live-air-health-title">Health Recommendations</h4>
                        <div className="vl-live-air-health-tabs" role="tablist" aria-label="Health recommendation profiles">
                          { HEALTH_PERSONAS.map( ( persona, idx ) => (
                            <button
                              key={ persona.id }
                              type="button"
                              role="tab"
                              id={ `vl-live-air-health-tab-${persona.id}` }
                              aria-controls="vl-live-air-health-panel"
                              aria-selected={ healthPersona === idx }
                              aria-label={ persona.label }
                              className={ `vl-live-air-health-tab ${healthPersona === idx ? 'is-active' : ''}`.trim() }
                              onClick={ () => setHealthPersona( idx ) }
                            >
              {/* Material-Symbols-EQUIVALENT glyph paths (filled, viewBox 0 0 24 24),
                  derived from Google's Material Symbols set so they read as the Google
                  icon family, drawn inline so the keyless path fires ZERO network calls.
                  general=groups, elderly=elderly, respiratory=pulmonology, heart=cardiology.
                  The active chip tints the glyph with --lime (see CSS). */}
                              <svg viewBox="0 0 24 24" aria-hidden="true" className="vl-live-air-health-icon">
                                { persona.icon === 'general' && (
                                  <path d="M12 12.75c1.63 0 3.07.39 4.24.9 1.08.48 1.76 1.56 1.76 2.73V18H6v-1.61c0-1.18.68-2.26 1.76-2.73 1.17-.52 2.61-.91 4.24-.91zM4 13c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm1.13 1.1c-.37-.06-.74-.1-1.13-.1-.99 0-1.93.21-2.78.58C.48 14.9 0 15.62 0 16.43V18h4.5v-1.61c0-.83.23-1.61.63-2.29zM20 13c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm4 3.43c0-.81-.48-1.53-1.22-1.85-.85-.37-1.79-.58-2.78-.58-.39 0-.76.04-1.13.1.4.68.63 1.46.63 2.29V18H24v-1.57zM12 6c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3z" />
                                ) }
                                { persona.icon === 'elderly' && (
                                  <path d="M14 3.5c0 1.1-.9 2-2 2s-2-.9-2-2 .9-2 2-2 2 .9 2 2zM10.5 22v-6H9l-2.6-6.5C6.07 8.68 5.3 8 4.4 8H4c-.83 0-1.5.67-1.5 1.5S3.17 11 4 11h.4l2.1 5.2V22h4zM16 22v-7h2V9c0-1.1-.9-2-2-2h-2.5c-.9 0-1.67.68-2 1.5L9 14l1.8.7 1.7-4.2V22H16z" />
                                ) }
                                { persona.icon === 'respiratory' && (
                                  <path d="M12 2c-1.1 0-2 .9-2 2v5.5H8.5V7c0-1.1-.9-2-2-2s-2 .9-2 2v9c0 2.21 1.79 4 4 4s4-1.79 4-4v-3.5h1V16c0 2.21 1.79 4 4 4s4-1.79 4-4V7c0-1.1-.9-2-2-2s-2 .9-2 2v2.5H14V4c0-1.1-.9-2-2-2zm-5.5 16c-1.1 0-2-.9-2-2v-4h2v4c0 .28.22.5.5.5s.5-.22.5-.5h1c0 1.1-.9 2-2 2zm11 0c-1.1 0-2-.9-2-2h1c0 .28.22.5.5.5s.5-.22.5-.5v-4h2v4c0 1.1-.9 2-2 2z" />
                                ) }
                                { persona.icon === 'heart' && (
                                  <path d="M13.5 2c-1.8 0-3.4 1-4.2 2.5C8.4 3 6.9 2 5 2 2.2 2 0 4.2 0 7c0 1.1.3 2.1.9 3H5l1-2 2 4 2.5-6 1.5 3 1-2h8.1c.6-.9.9-1.9.9-3 0-2.8-2.2-5-5-5-.47 0-.93.07-1.4.2V2zm-.1 18.3C14.9 19 20 14.6 21.1 12h-4.5l-1.5 3-3-6-2 5-1.4-2.8L7.9 12H2.9C4 14.6 9.1 19 10.6 20.3c.4.3.9.5 1.4.5s1-.2 1.4-.5z" />
                                ) }
                              </svg>
                            </button>
                          ) ) }
                          <button
                            type="button"
                            className="vl-live-air-health-next"
                            aria-label="Next recommendation profile"
                            onClick={ () => setHealthPersona( i => ( i + 1 ) % HEALTH_PERSONAS.length ) }
                          >
                            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
                          </button>
                        </div>
                        <hr className="vl-live-air-health-rule" aria-hidden="true" />
                        <div
                          className="vl-live-air-health-panel"
                          role="tabpanel"
                          id="vl-live-air-health-panel"
                          aria-labelledby={ `vl-live-air-health-tab-${HEALTH_PERSONAS[ healthPersona ].id}` }
                        >
                          <strong className="vl-live-air-health-persona">{ HEALTH_PERSONAS[ healthPersona ].label }</strong>
                          <p className="vl-live-air-health-text">{ HEALTH_PERSONAS[ healthPersona ].recommendation }</p>
                        </div>
                      </div>

                      {/* SECTION 3 - HOURLY HISTORY. Reuses the existing airHistory state and
                          historyRange/aqiCategory helpers. An inline-SVG AQI line chart over the
                          loaded points, weekday gridlines, a pinned current-value bubble and
                          prev/next navigation. The UTC timestamp is derived from the latest real
                          point - never fabricated. When airHistory is empty (every keyless run)
                          an honest shell renders with no fake chart and no spinner. */}
                      <div className="vl-live-air-history">
                        { ( () => {
                          if ( airHistory.length === 0 ) {
                            return (
                              <>
                                <div className="vl-live-air-history-head">
                                  <h4 className="vl-live-air-history-title">Hourly History</h4>
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
                          const d = new Date( current.time );
                          const pad = ( v: number ) => String( v ).padStart( 2, '0' );
                          const stamp = `${d.getUTCFullYear()}-${pad( d.getUTCMonth() + 1 )}-${pad( d.getUTCDate() )} ${pad( d.getUTCHours() )}:${pad( d.getUTCMinutes() )} UTC`;

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

                          // Weekday gridlines: one tick per UTC day boundary present in the
                          // series, labelled Mon..Sun from the point's own timestamp.
                          const WEEKDAYS = [ 'Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat' ];
                          const ticks: { x: number; label: string }[] = [];
                          let lastDay = -1;
                          points.forEach( ( p, i ) => {
                            const day = new Date( p.time ).getUTCDay();
                            if ( day !== lastDay ) {
                              ticks.push( { x: xAt( i ), label: WEEKDAYS[ day ] } );
                              lastDay = day;
                            }
                          } );

                          return (
                            <>
                              <div className="vl-live-air-history-head">
                                <h4 className="vl-live-air-history-title">Hourly History</h4>
                                <span className="vl-live-air-history-stamp">{ stamp }</span>
                              </div>
                              <div
                                className={ `vl-live-air-history-chart vl-live-air-sev-${aqiCategory( current.aqi ).sev}` }
                                role="img"
                                aria-label={ `AQI history, ${historyRangeLabel( historyRange )}, current ${Math.round( current.aqi )}` }
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
                                </svg>
                                <span className="vl-live-air-history-bubble" style={ { left: `${( cx / W ) * 100}%` } }>{ Math.round( current.aqi ) }</span>
                              </div>
                              <div className="vl-live-air-history-nav">
                                <button
                                  type="button"
                                  aria-label="Earlier hour"
                                  disabled={ offset >= maxOffset }
                                  onClick={ () => setHistoryOffset( o => Math.min( maxOffset, o + 1 ) ) }
                                >
                                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 6-6 6 6 6" /></svg>
                                </button>
                                <button
                                  type="button"
                                  aria-label="Later hour"
                                  disabled={ offset <= 0 }
                                  onClick={ () => setHistoryOffset( o => Math.max( 0, o - 1 ) ) }
                                >
                                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
                                </button>
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

                {/* PAGE FURNITURE, NOT LIVE DATA. Subscribe / Contribute / Share are the same
                    blocks every blog post carries, embedded here below the Air/Weather sections.
                    They render on EVERY path including keyless - they are SSR/keyless safe and
                    fire NO network call on mount (the Subscribe pill is a static WhatsApp anchor,
                    BlogContribution is a static WhatsApp anchor, ShareLinks only feature-detects
                    in an effect and writes classes). A hairline separator sits above them, and
                    BlogContribution runs embedded so it drops its own top rule inside the card.
                    None of the three render a <main>, so the single main.vl-live-shell landmark
                    is preserved.

                    SUBSCRIBE MATCHES THE LIVE BLOG POST, NOT THE OLD IN-PAGE FORM. The blog post
                    (src/pages/post/[slug].tsx) dropped the full BlogSubscribe signup box in favour
                    of a single compact lime pill that opens the Subscribe WhatsApp conversation -
                    the matched twin of BlogContribution's Contribute pill. We render that same
                    treatment INLINE here (so styled-jsx stamps its scope hash onto the markup):
                    a .vl-live-air-subscribe anchor at the shared SUBSCRIBE_CTA_HREF with a
                    .wc-sweep-note microcopy line below it, exactly as BlogContribution does. The
                    anchor is text-only (no glyph) and leaves the site, so it is a real <a> that is
                    middle-clickable, long-pressable and copyable; aria-label carries the visible
                    word for WCAG 2.5.3. The pill geometry is sized to the narrow (~336px) card
                    under .vl-live-air-extras rather than by editing the shared blog rules. */}
                <div className="vl-live-air-extras">
                  <hr className="vl-live-air-card-rule" aria-hidden="true" />
                  <a
                    className="vl-live-air-subscribe"
                    href={ SUBSCRIBE_CTA_HREF }
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label="Subscribe on WhatsApp"
                  >
                    <span>Subscribe</span>
                  </a>
                  <p className="wc-sweep-note" aria-hidden="true">Continue on WhatsApp →</p>
                  <BlogContribution postId="vayulok" slug="vayulok" embedded={ true } />
                  <ShareLinks url={ VAYULOK_PAGE_URL } title={ shareTitle } label="Share" />
                </div>
              </aside>

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
                  <div className={ `vl-live-map-canvas ${mapReady ? 'is-ready' : ''}` } ref={ mapHost } role="img" aria-label={ hasSelection ? `Map of ${place.name}` : 'Map of India' } />
                </>
              ) }

              { mapReady && (
                <div className="vl-live-map-search">
                  <label className="vl-live-sr-only" htmlFor="vl-live-search">Search a city or place</label>
                  <div className="vl-live-search">
                    <div className="vl-live-search-field">
                      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
                      <input
                        id="vl-live-search"
                        type="text"
                        role="combobox"
                        aria-controls="vl-live-search-results"
                        aria-expanded={ open }
                        aria-autocomplete="list"
                        autoComplete="off"
                        autoCorrect="off"
                        spellCheck={ false }
                        placeholder="Search a city or place"
                        value={ query }
                        onChange={ onQueryChange }
                        onFocus={ () => {
                          if ( query.trim() ) return;
                          const recent = recentPlaces().map( place => ( { name: place.name, addr: place.addr, place } ) );
                          setResults( recent ); setActive( recent.length ? 0 : -1 ); setOpen( recent.length > 0 ); setSearchStatus( 'idle' );
                        } }
                        onKeyDown={ onKeyDown }
                      />
                    </div>
                    <ul className="vl-live-search-results" id="vl-live-search-results" role="listbox" aria-label="Matching places" hidden={ !open || !results.length }>
                      { results.map( ( r, i ) => (
                        <li key={ `${r.name}-${r.addr}-${i}` } role="option" aria-selected={ i === active } onMouseDown={ e => { e.preventDefault(); void choose( r ); } }>
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

              { mapReady && (
                <div className="vl-live-layers" role="group" aria-label="Air quality layers">
                  <button type="button" disabled={ !hasSelection } aria-pressed={ layer === 'AQI' } onClick={ () => setLayer( v => v === 'AQI' ? null : 'AQI' ) }>AQI</button>
                  <button type="button" disabled={ !hasSelection } aria-pressed={ layer === 'PM25' } onClick={ () => setLayer( v => v === 'PM25' ? null : 'PM25' ) }>PM2.5</button>
                  <button type="button" disabled aria-pressed="false"><span className="vl-live-source-dot" />Observed</button>
                </div>
              ) }

              { liveActive && previewPlace.name && (
                <div className="vl-live-selected-label" aria-live="polite">
                  <strong>{ previewPlace.name }</strong>
                  { ( addressDescriptor || previewPlace.primaryType || previewPlace.addr ) && <span>{ addressDescriptor || previewPlace.primaryType || previewPlace.addr }</span> }
                </div>
              ) }
            </div>
          </section>
        </div>
      </main>

      <style jsx>{`
        .vl-live{
          --page:#fff;--alt:#fafafa;--lime:#d1f470;--lime-tint:rgba(209,244,112,.22);
          --green:#1a3a2a;--hair:#e5e7eb;--heading:rgba(0,0,0,.95);--body:rgba(0,0,0,.898);
          --muted:rgba(0,0,0,.54);--status:rgba(0,0,0,.70);--panel-r:14px;--pill-r:999px;
          /* Home semantic hues mirrored from src/styles/tokens.css so the card reads as
             multi-hue rather than near-mono. --info / --warning match tokens.css by name;
             --teal (#0f766e) and --status-green (#15803d) mirror tokens.css --status-delivered-fg
             and --status-read-fg (same values, local alias names). Used ONLY as section accents
             (title dots); the AQI severity ramp is untouched and severity meaning still comes from
             the category WORD + form, never hue alone (WCAG 1.4.1). No forbidden red. */
          --info:#1d4ed8;--warning:#b45309;--teal:#0f766e;--status-green:#15803d;
          font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:var(--body);background:var(--page);padding-bottom:72px;-webkit-font-smoothing:antialiased;
        }
        .vl-live,.vl-live *{box-sizing:border-box}
        .vl-live button,.vl-live input{font:inherit}
        .vl-live button{cursor:pointer}
        .vl-live button:focus-visible{outline:3px solid var(--green);outline-offset:3px}
        .vl-live input:focus-visible{outline:none}
        .vl-live-sr,.vl-live-sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
        .vl-live-shell{max-width:1320px;margin:0 auto;padding:22px 24px 72px}
        /* The map is now the full-width backdrop; the former two-column workspace
           collapses to a single region that the map shell fills edge to edge. */
        .vl-live-workspace{display:block}
        .vl-live-map-region{min-width:0}

        /* ── FLOATING AIR QUALITY CARD ───────────────────────────────────────────────
           A white, rounded, home-system card floating over the full-bleed map's top-left corner,
           inset so it clears Google's bottom-left logo and bottom-right legal notices.
           Scrollable so a long pollutant list never spills past the map. NO red. */
        .vl-live-air-card{position:absolute;z-index:12;top:16px;left:16px;width:min(336px,calc(100% - 32px));max-height:calc(100% - 150px);overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;padding:18px 18px 16px;border:1px solid var(--hair);border-radius:var(--panel-r);background:#fff;box-shadow:0 4px 12px rgba(0,0,0,.08);color:var(--body)}
        .vl-live-air-card-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
        .vl-live-air-card-title{margin:0;color:var(--heading);font-size:16px;font-weight:700;letter-spacing:-.2px}
        .vl-live-air-card-rule{margin:12px 0 14px;border:0;border-top:1px solid var(--hair)}

        /* EMBEDDED PAGE FURNITURE (Subscribe / Contribute / Share), MATCHED TO THE LIVE BLOG
           POST. The blog post (src/pages/post/[slug].tsx) carries a compact lime Subscribe pill
           (.blog-wa-subscribe) + microcopy, the twin of BlogContribution's Contribute pill
           (.bc-cta), then the ShareLinks row - NOT the old in-page BlogSubscribe form. This card
           renders the same furniture. BlogContribution self-styles; this wrapper owns the rhythm
           between the blocks inside the narrow (~336px) scrollable card and SIZES THE PILLS TO
           THE CARD so they do not overflow / look oversized, which is the owner's complaint.
           The card already scrolls (overflow-y:auto + scrollbar-width:thin, no colour), so added
           height just scrolls - we add NO scrollbar hider and NO thumb colour here. The embedded
           block's top gap is normalised so the blocks stack evenly under the hairline above. We
           do NOT edit the shared .bc-cta / .blog-wa-subscribe base rules (the blog page keeps its
           own geometry); the sizing is reached only via :global() nested under .vl-live-air-extras
           so the blog page is unaffected and its guard tests stay green. */
        .vl-live-air-extras{margin-top:16px;display:flex;flex-direction:column;gap:20px}
        .vl-live-air-extras :global(.bc){margin-top:0}

        /* THE SUBSCRIBE PILL, THE BLOG POST'S .blog-wa-subscribe OBJECT RENDERED INLINE HERE so
           styled-jsx scopes it. The values are the blog pill's: 2px #1a3a2a edge (clears
           WCAG 1.4.11 for a control boundary; the lime alone is 1.24:1), 50px pill radius,
           #1a3a2a type on #d1f470 lime (10.04:1), 17px/600 label and the house transition.
           SIZED TO THE CARD, which is the owner's ask: it is a full-width block pill (display:flex
           + width:100%) with reduced 20px inline padding and a slightly smaller 48px min-height
           instead of the blog's 52px / 0 28px that overflow the narrow column - still well above
           the 44px tap target. No margin-top: the hairline above and the flex gap own the rhythm,
           unlike the blog where it opens a band with margin-top:44px. */
        .vl-live-air-extras .vl-live-air-subscribe{
          display:flex;align-items:center;justify-content:center;box-sizing:border-box;width:100%;
          min-height:48px;padding:0 20px;border:2px solid #1a3a2a;border-radius:50px;
          background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;line-height:1.2;
          text-decoration:none;transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        /* THE HOUSE HOVER the owner mentions: lime -> white inversion with the one allowed lift
           and shadow. White gives #1a3a2a type 12.48:1. Mirrors .blog-wa-subscribe:hover and
           .bc-cta:hover exactly. */
        .vl-live-air-extras .vl-live-air-subscribe:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .vl-live-air-extras .vl-live-air-subscribe:active{transform:translateY(0)}
        .vl-live-air-extras .vl-live-air-subscribe:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
        /* REDUCED MOTION: drop the hover lift + shadow so this pill matches its Contribute twin,
           which carries the same @media(prefers-reduced-motion:reduce){ .bc-cta:hover{transform:none;
           box-shadow:none} } guard. The component's global .vl-live *{transition:none!important}
           already kills the animated transition, but not the static hover transform/shadow - this
           closes that asymmetry so the two matched pills behave identically. */
        @media(prefers-reduced-motion:reduce){
          .vl-live-air-extras .vl-live-air-subscribe:hover{transform:none;box-shadow:none}
        }

        /* SIZE THE EMBEDDED CONTRIBUTE PILL TO THE CARD. The shared .bc-cta ships inline-flex at
           padding:0 28px, which overflows this narrow column - the owner's "too big / not sized
           to the card". We reach it via :global() nested under .vl-live-air-extras ONLY, so the
           blog page's own .bc-cta is untouched (BlogContribution.test.tsx / BlogDesign.test.tsx
           pin the base rule and stay green). We match the Subscribe pill above: full-width block,
           20px inline padding, 48px min-height. We DO NOT re-declare colours, border, radius or
           the hover here - the shared rule already carries the lime->white inversion with
           translateY(-2px) + box-shadow:0 4px 12px rgba(26,58,42,.12), and this override only
           changes width/padding/height so that hover is preserved intact. */
        .vl-live-air-extras :global(.bc-cta){
          display:flex;width:100%;box-sizing:border-box;min-height:48px;padding:0 20px;
        }
        /* MICROCOPY line under each pill (the shared global .wc-sweep-note). Pull it up tight to
           its pill so the pill + its caption read as one object within the 20px flex gap. */
        .vl-live-air-extras :global(.wc-sweep-note){margin-top:8px}

        /* Air/Weather toggle - same pale tint + saturated same-hue dot as the hero pill. */
        .vl-live-air-toggle{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:3px;border:1px solid var(--hair);border-radius:var(--pill-r);background:#fff}
        .vl-live-air-toggle-btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:36px;border:0;border-radius:var(--pill-r);background:transparent;color:var(--green);font-size:12.5px;font-weight:700}
        .vl-live-air-toggle-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:rgba(26,58,42,.3)}
        .vl-live-air-toggle-btn.is-air.is-active{background:#e0f7c8}
        .vl-live-air-toggle-btn.is-air.is-active .vl-live-air-toggle-dot{background:#3da35a}
        .vl-live-air-toggle-btn.is-weather.is-active{background:#dbeafe;color:#1e3a5f}
        .vl-live-air-toggle-btn.is-weather.is-active .vl-live-air-toggle-dot{background:#2563eb}

        .vl-live-air-panel{margin-top:16px}
        .vl-live-air-empty{margin:0;padding:14px 0;color:var(--muted);font-size:12.5px;line-height:1.5}
        .vl-live-air-gauge-label{margin:0 0 10px;color:var(--green);font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
        .vl-live-air-gauge-row{display:flex;align-items:center;gap:16px}
        .vl-live-air-gauge{position:relative;flex:0 0 auto;width:96px;height:96px}
        .vl-live-air-gauge-svg{width:96px;height:96px;display:block}
        .vl-live-air-gauge-track{fill:none;stroke:var(--hair);stroke-width:10}
        /* The arc colour walks the no-red ramp mapped from air.sev. Severity is also
           carried by the number + category word, never by colour alone (WCAG 1.4.1). */
        .vl-live-air-gauge-arc{fill:none;stroke-width:10;stroke-linecap:round;transition:stroke-dasharray .4s ease}
        .vl-live-air-sev-good .vl-live-air-gauge-arc{stroke:#1a3a2a}
        .vl-live-air-sev-sat .vl-live-air-gauge-arc{stroke:#3da35a}
        .vl-live-air-sev-mod .vl-live-air-gauge-arc{stroke:#d1f470}
        .vl-live-air-sev-poor .vl-live-air-gauge-arc{stroke:#e8c547}
        .vl-live-air-sev-worst .vl-live-air-gauge-arc{stroke:#c98a2e}
        .vl-live-air-gauge-value{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--heading);font-size:28px;font-weight:700;letter-spacing:-.5px}
        .vl-live-air-gauge-meta{min-width:0}
        .vl-live-air-gauge-word{display:block;color:var(--heading);font-size:14.5px;font-weight:700;line-height:1.25}
        .vl-live-air-dominant{display:inline-flex;align-items:center;margin-top:8px;min-height:26px;padding:0 10px;border:1px solid var(--green);border-radius:var(--pill-r);background:var(--lime-tint);color:var(--green);font-size:10.5px;font-weight:700}

        .vl-live-air-pollutants{margin-top:18px}
        /* Section titles each carry a small on-palette accent dot (a distinct home hue
           per section) so the card reads multi-hue and cohesive with the home pages. The
           dot is decoration only - the section's meaning rests on its text label. */
        .vl-live-air-pollutants-title,.vl-live-air-heatmap-label,.vl-live-air-health-title,.vl-live-air-history-title{display:inline-flex;align-items:center;gap:7px}
        .vl-live-air-pollutants-title::before,.vl-live-air-heatmap-label::before,.vl-live-air-health-title::before,.vl-live-air-history-title::before{content:"";flex:0 0 auto;width:7px;height:7px;border-radius:50%}
        .vl-live-air-pollutants-title::before{background:var(--teal)}
        .vl-live-air-heatmap-label::before{background:var(--info)}
        .vl-live-air-health-title::before{background:var(--status-green)}
        .vl-live-air-history-title::before{background:var(--warning)}
        .vl-live-air-pollutants-title{margin:0 0 10px;color:var(--heading);font-size:12.5px;font-weight:700;letter-spacing:-.1px}
        /* overflow:visible (was hidden) so the side popover below can escape the list box
           and float beside its row without being clipped. The list keeps its rounded 12px
           frame; the first/last rows round their own outer corners so the row fills still
           follow the frame now that the list no longer clips them. No scrollbar colour and
           no scrollbar hider are introduced here (the card keeps only scrollbar-width:thin). */
        .vl-live-air-pollutant-list{margin:0;padding:0;list-style:none;border:1px solid var(--hair);border-radius:12px;overflow:visible}
        .vl-live-air-pollutant-row{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:12px;padding:11px 13px;background:#fff;border-left:2px solid transparent;transition:background .15s ease,border-color .15s ease}
        .vl-live-air-pollutant-row:first-child{border-top-left-radius:11px;border-top-right-radius:11px}
        .vl-live-air-pollutant-row:last-child{border-bottom-left-radius:11px;border-bottom-right-radius:11px}
        .vl-live-air-pollutant-row+.vl-live-air-pollutant-row{border-top:1px solid var(--hair)}
        .vl-live-air-pollutant-value{color:var(--heading);font-size:14px;font-weight:700;letter-spacing:-.2px}
        .vl-live-air-pollutant-value small{margin-left:3px;color:var(--muted);font-size:10px;font-weight:600;letter-spacing:0}
        .vl-live-air-pollutant-label{color:var(--status);font-size:12px;font-weight:600}
        /* Custom pollutant tooltip: shows the label+value+unit (or Sources/Effects) on
           hover AND keyboard focus (the native title= was unreliable and is gone). The tip
           is rendered inline so styled-jsx can scope it, carries a literal z-index:1700
           (matching the home --z-tooltip:1700 scale in tokens.css), and is wired to the
           trigger via aria-describedby. NO red.

           POSITIONING (Google Maps Platform reference): the tip opens BESIDE its row,
           floated to the SIDE of the ⓘ trigger and vertically centred on it, instead of the
           old bottom:calc(100% + 8px);right:0 that opened UPWARD over the rows above and got
           its first Sources line clipped when the row sat near the bottom of the scrolling
           card. It now anchors horizontally off the trigger (right:calc(100% + 12px)) so it
           never stacks over the rows above/below, and because the .vl-live-air-pollutant-list
           above no longer clips (overflow:visible) the panel floats clear of the list frame.
           It stays attached to its own ⓘ via the vertical centre + the entry slide that moves
           in horizontally from the trigger. Hover + focus-visible + focus-within all show it,
           so it is reachable by pointer AND keyboard. */
        .vl-live-air-pollutant-info{position:relative;display:inline-flex;align-items:center;justify-content:center;cursor:help;border-radius:50%}
        .vl-live-air-pollutant-info svg{width:15px;height:15px;stroke:var(--info);fill:none;stroke-width:1.6;stroke-linecap:round;transition:stroke .15s ease}
        .vl-live-air-pollutant-info:hover svg,.vl-live-air-pollutant-info:focus-visible svg{stroke:var(--lime)}
        .vl-live-air-pollutant-info:focus-visible{outline:none;box-shadow:0 0 0 3px rgba(209,244,112,.45)}
        .vl-live-air-pollutant-tip{position:absolute;top:50%;right:calc(100% + 12px);bottom:auto;left:auto;z-index:1700;width:max-content;max-width:230px;padding:11px 13px;border-radius:12px;border:1px solid var(--hair);background:#fff;color:var(--status);font-size:11px;font-weight:500;line-height:1.4;text-align:left;box-shadow:0 10px 28px rgba(0,0,0,.16);opacity:0;visibility:hidden;transform:translate(6px,-50%);transition:opacity .15s ease,transform .15s ease,visibility .15s ease;pointer-events:none}
        .vl-live-air-pollutant-info:hover .vl-live-air-pollutant-tip,.vl-live-air-pollutant-info:focus-visible .vl-live-air-pollutant-tip,.vl-live-air-pollutant-info:focus-within .vl-live-air-pollutant-tip{opacity:1;visibility:visible;transform:translate(0,-50%)}
        .vl-live-air-pollutant-pop{display:flex;flex-direction:column;gap:3px}
        .vl-live-air-pollutant-pop-title{display:inline-block;align-self:flex-start;margin-bottom:4px;padding:2px 8px;border-radius:6px;background:var(--lime);color:var(--heading);font-size:12px;font-weight:700;letter-spacing:.1px}
        .vl-live-air-pollutant-pop-head{margin-top:5px;color:var(--heading);font-size:11px;font-weight:700}
        .vl-live-air-pollutant-pop-head:first-of-type{margin-top:0}
        .vl-live-air-pollutant-pop-text{color:var(--muted);font-size:11px;font-weight:500;line-height:1.45}
        .vl-live-air-pollutant-row:focus-within,.vl-live-air-pollutant-row:hover{background:rgba(209,244,112,.18);border-left-color:var(--lime)}

        /* ── HEATMAP (toggle + Poor->Excellent legend) ──────────────────────────────
           The switch drives the existing deck.gl AQI overlay via the layer state. On/off is
           carried by aria-checked AND the is-on knob position. The legend gradient and the
           Poor/Excellent words sit on the approved no-red ramp - never any red hex. */
        .vl-live-air-heatmap{margin-top:18px}
        .vl-live-air-heatmap-row{display:flex;align-items:center;justify-content:space-between;gap:12px}
        .vl-live-air-heatmap-row+.vl-live-air-heatmap-row{margin-top:10px}
        .vl-live-air-heatmap-label{color:var(--heading);font-size:12.5px;font-weight:700;letter-spacing:-.1px}
        /* Switch restyled to the HOME control idiom: 2px border, lime ON track with a dark
           --green knob (the brand toggle look), and the home lime --focus-ring on
           :focus-visible. role=switch / aria-checked / aria-label / disabled wiring is
           unchanged in the markup; styling only. NO red. */
        .vl-live-air-heatmap-switch{position:relative;flex:0 0 auto;width:44px;height:24px;padding:0;border:2px solid var(--hair);border-radius:999px;background:#eef1ed;transition:background .18s ease,border-color .18s ease,box-shadow .18s ease}
        .vl-live-air-heatmap-switch.is-on{background:var(--lime);border-color:var(--green)}
        .vl-live-air-heatmap-switch:focus-visible{outline:none;box-shadow:0 0 0 3px rgba(209,244,112,.45)}
        .vl-live-air-heatmap-switch:disabled{opacity:.5;cursor:not-allowed}
        .vl-live-air-heatmap-knob{position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .18s ease,background .18s ease}
        .vl-live-air-heatmap-switch.is-on .vl-live-air-heatmap-knob{transform:translateX(20px);background:var(--green)}
        .vl-live-air-heatmap-legend{margin-top:10px}
        .vl-live-air-heatmap-ramp{display:block;height:8px;border-radius:999px;background:linear-gradient(90deg,#c98a2e 0%,#e8c547 42%,#d1f470 74%,#3da35a 100%)}
        .vl-live-air-heatmap-ends{display:flex;align-items:center;justify-content:space-between;margin-top:5px}
        .vl-live-air-heatmap-end{color:var(--muted);font-size:10.5px;font-weight:700;letter-spacing:.02em}

        /* ── HEALTH RECOMMENDATIONS (persona tablist + advisory) ─────────────────────
           Selected persona highlight is brand green/lime UI chrome (NOT a severity colour,
           NOT red). Icons are aria-hidden; each tab has an accessible name. */
        .vl-live-air-health{margin-top:20px}
        .vl-live-air-health-title{margin:0 0 10px;color:var(--heading);font-size:12.5px;font-weight:700;letter-spacing:-.1px}
        .vl-live-air-health-tabs{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
        .vl-live-air-health-tab{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;padding:0;border:1px solid var(--hair);border-radius:50%;background:#fff;color:var(--green)}
        .vl-live-air-health-tab:focus-visible{outline:none;box-shadow:0 0 0 3px rgba(209,244,112,.45)}
        .vl-live-air-health-tab.is-active{background:var(--green);border-color:var(--green);color:var(--lime);box-shadow:0 0 0 2px var(--lime-tint)}
        .vl-live-air-health-tab.is-active:focus-visible{box-shadow:0 0 0 3px rgba(209,244,112,.45)}
        /* Material-Symbols-style glyphs are filled paths; the active chip tints them --lime
           via currentColor (set by .is-active above), inactive stays brand --green. */
        .vl-live-air-health-icon{width:21px;height:21px;fill:currentColor;stroke:none}
        .vl-live-air-health-next{display:inline-flex;align-items:center;justify-content:center;width:32px;height:40px;padding:0;border:0;background:transparent;color:var(--muted)}
        .vl-live-air-health-next svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
        .vl-live-air-health-rule{margin:14px 0 12px;border:0;border-top:1px solid var(--hair)}
        .vl-live-air-health-persona{display:block;color:var(--heading);font-size:13px;font-weight:700}
        .vl-live-air-health-text{margin:6px 0 0;color:var(--body);font-size:12px;line-height:1.55}

        /* ── HOURLY HISTORY (inline-SVG AQI chart) ──────────────────────────────────
           Line + area stroked from the no-red ramp via the sev-mapped class; the pinned
           bubble shows the current AQI number so meaning never rests on colour alone. */
        .vl-live-air-history{margin-top:20px}
        .vl-live-air-history-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px}
        .vl-live-air-history-title{margin:0;color:var(--heading);font-size:12.5px;font-weight:700;letter-spacing:-.1px}
        .vl-live-air-history-stamp{color:var(--muted);font-size:10.5px;font-weight:600;letter-spacing:.01em}
        .vl-live-air-history-empty{margin:12px 0 0;color:var(--muted);font-size:12px;line-height:1.5}
        .vl-live-air-history-chart{position:relative;margin-top:12px}
        .vl-live-air-history-svg{display:block;width:100%;height:120px}
        .vl-live-air-history-grid{stroke:var(--hair);stroke-width:1;stroke-dasharray:2 3}
        .vl-live-air-history-day{fill:var(--muted);font-size:8px;font-weight:600}
        .vl-live-air-history-leader{stroke:var(--muted);stroke-width:1;stroke-dasharray:2 2}
        .vl-live-air-history-line{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
        .vl-live-air-history-area{fill:currentColor;opacity:.12;stroke:none}
        .vl-live-air-history-dot{stroke:#fff;stroke-width:2}
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
        .vl-live-air-history-bubble{position:absolute;top:0;transform:translateX(-50%);min-width:28px;padding:2px 7px;border:1px solid var(--green);border-radius:999px;background:#fff;color:var(--green);font-size:11px;font-weight:700;text-align:center}
        .vl-live-air-history-nav{display:flex;justify-content:flex-end;gap:6px;margin-top:8px}
        .vl-live-air-history-nav button{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;padding:0;border:1px solid var(--hair);border-radius:50%;background:#fff;color:var(--green)}
        .vl-live-air-history-nav button:disabled{opacity:.4;cursor:not-allowed}
        .vl-live-air-history-nav svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}

        /* FULL-BLEED MAP. The map reads edge-to-edge: no border, no rounded box. overflow:hidden
           still clips the heatmap tiles + overlays, isolation:isolate keeps the overlay z-stack
           contained, and the height band is unchanged. The floating .vl-live-air-card and the
           on-map controls stay positioned over the now edge-to-edge map, and the card's bottom
           inset still clears Google's bottom-left logo and bottom-right legal corners. */
        .vl-live-map-shell{position:relative;height:72dvh;min-height:620px;max-height:860px;overflow:hidden;background:#eef1ed;isolation:isolate}
        .vl-live-map-canvas,.vl-live-map-placeholder{position:absolute;inset:0;width:100%;height:100%}
        .vl-live-map-canvas{opacity:0}
        .vl-live-map-canvas.is-ready{opacity:1}
        .vl-live-map-placeholder{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding:24px;text-align:center;z-index:0;background:#eef1ed;color:var(--green)}
        .vl-live-map-placeholder strong{font-size:15px;letter-spacing:-.01em}
        .vl-live-map-placeholder span{font-size:12.5px;color:var(--muted)}
        .vl-live-map-placeholder p{margin:4px 0 0;font-size:12px;color:var(--status)}
        .vl-live-map-fallback{position:absolute;inset:0;display:grid;place-items:center;z-index:0;background:#eef1ed;color:var(--green);font-size:13px}
        .vl-live-map-fallback button{margin-left:8px;border:1px solid var(--green);border-radius:999px;background:#fff;color:var(--green);padding:7px 11px}
        .vl-live-map-search{position:absolute;z-index:10;top:16px;left:50%;transform:translateX(-50%);width:min(430px,calc(100% - 190px))}
        .vl-live-search{position:relative}
        /* THE SITE-WIDE SEARCH LOOK, adopted from BlogSearch.tsx (the canonical global field):
           a borderless input with a single 1px bottom hairline (var(--hair)), no pill rounding
           and no heavy drop shadow. On focus the hairline darkens to the opaque brand green
           (var(--green) #1a3a2a, 12.48:1 on white, which clears WCAG 1.4.11) with the small lime
           underline box-shadow:0 1px 0 0 #d1f470 - the identical focus treatment the blog/menu
           search uses. The combobox markup + a11y (role=combobox, aria-controls/expanded/
           autocomplete, the listbox/option results, keyboard nav) and the India gating are
           UNCHANGED - this is purely the field's VISUAL idiom. Because the field floats OVER the
           map it keeps an opaque white backing on the container so it stays legible, but drops the
           box so it reads as the site's borderless-with-hairline search rather than a pill. */
        .vl-live-search-field{height:50px;display:flex;align-items:center;gap:10px;padding:0 12px;background:#fff;border-radius:10px}
        .vl-live-search-field svg{width:19px;height:19px;stroke:var(--green);fill:none;stroke-width:2;flex:0 0 auto}
        .vl-live-search-field input{width:100%;height:100%;padding:0 2px;border:0;border-bottom:1px solid var(--hair);border-radius:0;outline:none;background:transparent;color:var(--heading);font-size:17px;transition:border-color .2s,box-shadow .2s}
        .vl-live-search-field input::placeholder{color:rgba(0,0,0,.44)}
        .vl-live-search-field input:focus-visible{border-bottom-color:var(--green);box-shadow:0 1px 0 0 #d1f470}
        .vl-live-search-results{position:absolute;top:56px;left:0;right:0;z-index:20;margin:0;padding:6px;list-style:none;border:1px solid var(--hair);border-radius:14px;background:#fff;box-shadow:0 8px 22px rgba(26,58,42,.12)}
        .vl-live-search-results li{padding:10px 12px;border-radius:10px;cursor:pointer}
        .vl-live-search-results li[aria-selected="true"]{background:var(--lime-tint)}
        .vl-live-search-results strong,.vl-live-search-results span{display:block}
        .vl-live-search-results strong{font-size:13px;color:var(--heading)}
        .vl-live-search-results span{margin-top:2px;font-size:11px;color:var(--muted)}
        .vl-live-search-status{margin:6px 8px 0;font-size:11px;color:var(--muted)}
        .vl-live-layers{position:absolute;z-index:10;right:16px;top:78px;display:flex;gap:6px;padding:3px;border:1px solid rgba(26,58,42,.13);border-radius:999px;background:rgba(255,255,255,.92)}
        .vl-live-layers button{height:36px;min-height:36px;padding:0 12px;border:0;border-radius:999px;background:transparent;color:var(--green);font-size:11.5px;font-weight:700}
        .vl-live-layers button:hover{background:rgba(209,244,112,.18)}
        .vl-live-layers button[aria-pressed="true"]{background:rgba(209,244,112,.60);box-shadow:inset 0 0 0 1px rgba(26,58,42,.22)}
        .vl-live-layers button:disabled{opacity:1;color:rgba(26,58,42,.62);cursor:default}
        .vl-live-source-dot{display:inline-block;width:8px;height:8px;margin-right:6px;border-radius:50%;background:var(--lime);box-shadow:0 0 0 1px var(--green)}
        .vl-live-selected-label{position:absolute;z-index:11;left:50%;bottom:28px;transform:translateX(-50%);width:auto;max-width:min(500px,calc(100% - 92px));min-height:46px;display:flex;align-items:center;justify-content:center;gap:9px;padding:8px 15px;border:1px solid rgba(26,58,42,.14);border-radius:999px;background:#fff;text-align:center;box-shadow:0 5px 18px rgba(26,58,42,.07)}
        .vl-live-selected-label strong{font-size:12px;color:var(--heading);letter-spacing:.035em;text-transform:uppercase}
        .vl-live-selected-label span{font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .vl-live-selected-label span::before{content:'·';margin-right:8px;color:rgba(26,58,42,.45)}

        @media(max-width:1050px){
          .vl-live-map-shell{height:66dvh;min-height:560px}
        }
        @media(max-width:700px){
          .vl-live-shell{padding:10px 10px 44px}
          .vl-live-map-shell{height:62dvh;min-height:460px;max-height:640px}
          .vl-live-map-search{top:10px;width:calc(100% - 20px)}
          .vl-live-layers{top:70px;right:10px}
          .vl-live-selected-label{bottom:22px;width:calc(100% - 20px);max-width:none}
          /* The floating card narrows and stays inset so it keeps the map and the
             bottom attribution corners usable on small screens. */
          .vl-live-air-card{top:10px;left:10px;width:calc(100% - 20px);max-width:300px;max-height:calc(100% - 170px);padding:14px 14px 12px}
          .vl-live-air-gauge,.vl-live-air-gauge-svg{width:84px;height:84px}
        }
        @media(max-height:500px) and (orientation:landscape){
          .vl-live-shell{padding-top:8px}
          .vl-live-map-shell{height:calc(100dvh - 24px);min-height:250px}
          .vl-live-search-field{height:44px}
          .vl-live-layers{top:64px}
          .vl-live-air-card{max-height:calc(100% - 20px)}
        }
        @media(prefers-reduced-motion:reduce){
          .vl-live *{scroll-behavior:auto!important;transition:none!important}
        }
      `}</style>
    </section>
  );
};

export default VayuLokLive;