import React, { useCallback, useEffect, useRef, useState } from 'react';

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
 * any failed call simply omits its fields rather than showing broken state.
 *
 * ON USER ACTION ONLY. The AQI air-quality dot overlay is created ONLY when the user presses
 * a layer-control button. It is never requested on page load.
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

// India bounds, so the map cannot be panned off the product's area. Verbatim from the
// mock's map options.
const INDIA_BOUNDS = { north: 37.6, south: 6.4, west: 68.1, east: 97.4 };

// Neutral map camera; no place is selected until the visitor acts.
interface PlacePhotoAttribution {
  name: string;
  uri?: string;
}
interface PlacePhoto {
  url: string;
  attributions: PlacePhotoAttribution[];
}
interface PlaceState {
  name: string;
  addr: string;
  lat: number;
  lng: number;
  // Retain the resolved Google Place ID so a future server-side Geocoding v4
  // SearchDestinations relay can enrich discrete destinations without re-searching.
  placeId?: string;
  photos?: PlacePhoto[];
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
  photos?: {
    getURI?: ( opts: { maxWidth?: number; maxHeight?: number } ) => string;
    authorAttributions?: { displayName?: string; uri?: string }[];
  }[];
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

/* Hard India gate. Region/country restrictions bias Google results, but border locations can
   still resolve outside India. Accept only an explicit country short code of IN; support both
   classic Geocoder address_components and modern Place addressComponents shapes. */
function isIndiaResult( result: unknown ): boolean {
  if ( !result || typeof result !== 'object' ) return false;
  const r = result as {
    address_components?: { types?: string[]; short_name?: string }[];
    addressComponents?: { types?: string[]; shortText?: string }[];
  };
  const components = Array.isArray( r.address_components )
    ? r.address_components
    : ( Array.isArray( r.addressComponents ) ? r.addressComponents : [] );
  for ( const component of components ) {
    if ( !component || !Array.isArray( component.types ) || !component.types.includes( 'country' ) ) continue;
    const code = ( ( component as { short_name?: string } ).short_name
      || ( component as { shortText?: string } ).shortText || '' ).toUpperCase();
    return code === 'IN';
  }
  return false;
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
  photos: [],
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
  pollutants: { code: string; label: string; value: number; unit: string }[];
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
  const WANT: Record<string, string> = {
    pm25: 'PM2.5', pm10: 'PM10', no2: 'NO\u2082', o3: 'O\u2083', co: 'CO', so2: 'SO\u2082',
  };
  ( data?.pollutants || [] ).forEach( ( p: { code?: string; concentration?: { value?: number; units?: string } } ) => {
    const label = p.code ? WANT[ p.code ] : undefined;
    const v = p.concentration?.value;
    if ( label && Number.isFinite( v ) ) {
      pollutants.push( { code: p.code as string, label, value: v as number, unit: concUnitLabel( p.concentration?.units ) } );
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
    // Do not persist Google photo URIs. Maps Platform photo URLs must be obtained
    // from a fresh Place object, and any supplied author attribution must travel
    // with the displayed photo.
    rows.unshift( { name: place.name, addr: place.addr, lat: place.lat, lng: place.lng, photos: [] } );
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
  const [ photoIndex, setPhotoIndex ] = useState( 0 );
  const [ searchStatus, setSearchStatus ] = useState<'idle' | 'searching' | 'no-results' | 'unavailable' | 'outside-india'>( 'idle' );

  const [ air, setAir ] = useState<AirState | null>( null );
  const [ weather, setWeather ] = useState<WeatherState | null>( null );
  const [ pollen, setPollen ] = useState<PollenRow[] | null>( null );
  const [ weatherHourly, setWeatherHourly ] = useState<WeatherHour[]>( [] );
  const [ weatherHistory, setWeatherHistory ] = useState<WeatherHour[]>( [] );
  const [ weatherDaily, setWeatherDaily ] = useState<WeatherDay[]>( [] );
  const [ weatherAlerts, setWeatherAlerts ] = useState<WeatherAlertRow[]>( [] );
  const [ airForecast, setAirForecast ] = useState<AirPoint[]>( [] );
  const [ airHistory, setAirHistory ] = useState<AirPoint[]>( [] );
  const [ historyRange, setHistoryRange ] = useState<24 | 168 | 720>( 24 );
  const [ historyLoading, setHistoryLoading ] = useState( false );
  const [ dataLoading, setDataLoading ] = useState( false );
  const [ coreError, setCoreError ] = useState( false );
  const [ refreshNonce, setRefreshNonce ] = useState( 0 );
  const [ coreFetchedAt, setCoreFetchedAt ] = useState<number | null>( null );
  const [ mapCandidate, setMapCandidate ] = useState<PlaceState | null>( null );
  const [ nearbyPhotos, setNearbyPhotos ] = useState<PlacePhoto[]>( [] );
  const [ addressDescriptor, setAddressDescriptor ] = useState( '' );
  const [ elevationM, setElevationM ] = useState<number | null>( null );

  // Search combobox state.
  const [ query, setQuery ] = useState( '' );
  const [ results, setResults ] = useState<SearchResult[]>( [] );
  const [ open, setOpen ] = useState( false );
  const [ active, setActive ] = useState( -1 );

  // Which air-quality layer is active (user action only). null = none on load. Selecting a
  // layer both toggles the map air-quality layer AND swaps the environmental RESULT content shown
  // in the LEFT card (AQI result vs PM2.5-focused result).
  const [ layer, setLayer ] = useState<'AQI' | 'PM25' | null>( null );

  const mapHost = useRef<HTMLDivElement | null>( null );
  const photoRailRef = useRef<HTMLDivElement | null>( null );
  const placeCardRef = useRef<HTMLDivElement | null>( null );
  const mapRef = useRef<unknown>( null );
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
  const gridAbortRef = useRef<AbortController | null>( null );
  const gridCache = useRef<Record<string, { ts: number; dots: AirDot[]; center: AirState | null }>>( {} );

  useEffect( () => {
    setPhotoIndex( 0 );
    setMapCandidate( null );
    setNearbyPhotos( [] );
    setAddressDescriptor( '' );
    setElevationM( null );
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
        center: { lat: DEFAULT_PLACE.lat, lng: DEFAULT_PLACE.lng },
        zoom: 13,
        mapTypeId: 'roadmap',
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
        restriction: { latLngBounds: INDIA_BOUNDS, strictBounds: true },
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
        gc?.geocode?.( { location: { lat, lng }, region: 'in', extraComputations: [ 'ADDRESS_DESCRIPTORS' ] }, async ( rows, status ) => {
          if ( status !== 'OK' || !Array.isArray( rows ) || !rows.length ) return;
          const first = rows.find( row => isIndiaResult( row ) ) as
            | { formatted_address?: string; place_id?: string }
            | undefined;
          if ( !first ) {
            setSearchStatus( 'outside-india' );
            return;
          }
          const next: PlaceState = {
            name: first.formatted_address?.split( ',' )[ 0 ] || 'Selected location',
            addr: first.formatted_address || '',
            lat,
            lng,
            placeId: first.place_id,
            photos: [],
          };
          setHasSelection( true );
          setSearchStatus( 'idle' );
          // 03C - selecting an area (here via a map click) recenters the map on that
          // area's geocoded lat/lng and loads its live data, exactly like choosing a
          // search result. The recenter effect (center + zoom 14 + marker move) fires on
          // the place change, so only the selected area's geocoding is shown. mapCandidate
          // continues to drive the photo overlay / nearby-media enrichment below.
          setMapCandidate( next );
          setPlace( next );

          // If reverse geocoding produced a Place ID, enrich the preview with Google
          // Places photos AND the honest metadata the left card can show. Any author
          // attribution supplied by Google is preserved and rendered with the photo below.
          if ( first.place_id ) {
            const lib = placesLibRef.current as {
              Place?: new ( opts: { id: string } ) => GooglePlaceLike;
            } | null;
            const PlaceCtor = lib?.Place;
            if ( PlaceCtor ) {
              try {
                const googlePlace = new PlaceCtor( { id: first.place_id } );
                await googlePlace.fetchFields?.( { fields: [ 'photos', ...PLACE_META_FIELDS ] } );
                const photos: PlacePhoto[] = ( Array.isArray( googlePlace.photos ) ? googlePlace.photos : [] )
                  .slice( 0, 8 )
                  .map( photo => ( {
                    url: photo.getURI?.( { maxWidth: 900, maxHeight: 600 } ) || '',
                    attributions: ( Array.isArray( photo.authorAttributions ) ? photo.authorAttributions : [] )
                      .map( a => ( { name: String( a.displayName || 'Photo contributor' ), uri: a.uri } ) ),
                  } ) )
                  .filter( photo => Boolean( photo.url ) );
                const meta = metaFromGooglePlace( googlePlace );
                if ( photos.length || Object.keys( meta ).length ) {
                  const enrich = { ...meta, ...( photos.length ? { photos } : {} ) };
                  setMapCandidate( current => current && current.lat === lat && current.lng === lng
                    ? { ...current, ...enrich }
                    : current );
                  setPlace( current => current.lat === lat && current.lng === lng
                    ? { ...current, ...enrich }
                    : current );
                }
              } catch { /* photo + metadata enrichment is optional */ }
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
     PLACE CARD MEDIA FALLBACK. Exact-place photos are preferred. If none are available,
     look for nearby photographed Places. Only then use a tightly-contained Street View
     panorama inside the place card; the main map remains a normal roadmap. */
  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' || !mapReady ) return;
    const target = mapCandidate || place;
    const hasExactPhoto = ( target.photos || [] ).some( photo => Boolean( photo.url ) );
    if ( hasExactPhoto ) {
      setNearbyPhotos( [] );
      return;
    }

    let cancelled = false;
    setNearbyPhotos( [] );

    const loadMedia = async () => {
      const lib = placesLibRef.current as {
        Place?: {
          searchNearby?: ( req: Record<string, unknown> ) => Promise<{ places?: any[] }>;
        };
      } | null;

      try {
        const searchNearby = lib?.Place?.searchNearby;
        if ( typeof searchNearby === 'function' ) {
          const out = await searchNearby( {
            fields: [ 'displayName', 'location', 'photos' ],
            locationRestriction: { center: { lat: target.lat, lng: target.lng }, radius: 2500 },
            maxResultCount: 8,
            rankPreference: 'DISTANCE',
          } );
          const photos: PlacePhoto[] = [];
          ( Array.isArray( out?.places ) ? out.places : [] ).forEach( p => {
            ( Array.isArray( p?.photos ) ? p.photos : [] ).slice( 0, 2 ).forEach( ( photo: any ) => {
              const url = photo?.getURI?.( { maxWidth: 1200, maxHeight: 760 } ) || '';
              if ( !url ) return;
              const attributions = ( Array.isArray( photo?.authorAttributions ) ? photo.authorAttributions : [] )
                .map( ( a: any ) => ( { name: String( a?.displayName || 'Photo contributor' ), uri: a?.uri } ) );
              photos.push( { url, attributions } );
            } );
          } );
          if ( !cancelled && photos.length ) {
            setNearbyPhotos( photos.slice( 0, 8 ) );
            return;
          }
        }
      } catch { /* nearby photo enrichment is optional */ }

      // No Street View fallback here. A native panorama brings its own chrome and
      // visual language into the card; the neutral fallback below keeps the VayuLok card stable.
    };

    const id = window.setTimeout( () => { void loadMedia(); }, 0 );
    return () => {
      cancelled = true;
      window.clearTimeout( id );
    };
  }, [ mapReady, mapCandidate, place, hasSelection ] );

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
     (6) on deactivate/unmount clears the overlay and aborts any in-flight grid fetch. */
  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;
    // No layer active -> ensure overlay is detached and the single-point air result clears.
    if ( !layer ) {
      const existing = deckOverlayRef.current as { setMap?: ( m: unknown ) => void; setProps?: ( p: { layers: unknown[] } ) => void } | null;
      existing?.setProps?.( { layers: [] } );
      existing?.setMap?.( null );
      requestAnimationFrame( () => { setDataLoading( false ); } );
      return;
    }
    const map = mapRef.current;
    if ( !map ) return;

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
              ],
              languageCode: 'en',
              universalAqi: true,
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
        const WANT: Record<string, string> = {
          pm25: 'PM2.5', pm10: 'PM10', no2: 'NO\u2082', o3: 'O\u2083', co: 'CO', so2: 'SO\u2082',
        };
        ( data?.pollutants || [] ).forEach( ( p: { code?: string; concentration?: { value?: number; units?: string } } ) => {
          const label = p.code ? WANT[ p.code ] : undefined;
          const v = p.concentration?.value;
          if ( label && Number.isFinite( v ) ) {
            pollutants.push( { code: p.code as string, label, value: v as number, unit: concUnitLabel( p.concentration?.units ) } );
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
      // Branded selected-place marker. Created lazily after the first valid India selection.
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
    if ( place.viewport && map.fitBounds ) map.fitBounds( place.viewport, 56 );
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
     selection session. This avoids legacy Text Search on every keystroke and keeps
     results hard-restricted to India. Geocoding remains only as an unavailable-Places
     fallback. */
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
     Place enrichment used by the approved v8 card. Both calls are optional and disappear
     cleanly when a project has not enabled the corresponding service. */
  useEffect( () => {
    if ( !MAPS_KEY || !hasSelection || !mapReady || typeof window === 'undefined' ) return;
    let cancelled = false;

    const describe = async () => {
      const gc = await ensureGeocoder();
      if ( !gc?.geocode || cancelled ) return;
      const request: Record<string, unknown> = place.placeId
        ? { placeId: place.placeId, region: 'in', extraComputations: [ 'ADDRESS_DESCRIPTORS' ] }
        : { location: { lat: place.lat, lng: place.lng }, region: 'in', extraComputations: [ 'ADDRESS_DESCRIPTORS' ] };
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

    const elevate = async () => {
      try {
        const maps = ( window as any )?.google?.maps;
        const lib = maps?.importLibrary ? await maps.importLibrary( 'elevation' ) : null;
        const ElevationService = lib?.ElevationService || maps?.ElevationService;
        if ( cancelled || !ElevationService ) return;
        const service = new ElevationService();
        const response = await service.getElevationForLocations( { locations: [ { lat: place.lat, lng: place.lng } ] } );
        const value = response?.results?.[ 0 ]?.elevation;
        if ( !cancelled && Number.isFinite( value ) ) setElevationM( Math.round( value ) );
      } catch { /* elevation is optional */ }
    };

    void describe();
    void elevate();
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
          includedRegionCodes: [ 'in' ],
          region: 'in',
          locationRestriction: INDIA_BOUNDS,
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

    // Fallback for a partial Maps load: Geocoding is still India restricted. The Geocoder
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
      { address: text, componentRestrictions: { country: 'in' }, region: 'in' },
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
          .filter( ( row: unknown ) => isIndiaResult( row ) )
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
              photos: [],
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
    searchTimer.current = setTimeout( () => { void runSearch( v ); }, 300 );
  };

  const choose = useCallback( async ( r: SearchResult ) => {
    let next = r.place;
    if ( !next && r.prediction?.toPlace ) {
      try {
        const googlePlace = r.prediction.toPlace();
        await googlePlace.fetchFields?.( { fields: [ 'id', 'displayName', 'formattedAddress', 'location', 'addressComponents', 'photos', ...PLACE_META_FIELDS ] } );
        if ( !isIndiaResult( googlePlace ) ) {
          setSearchStatus( 'outside-india' );
          return;
        }
        const lat = googlePlace.location?.lat?.();
        const lng = googlePlace.location?.lng?.();
        if ( Number.isFinite( lat ) && Number.isFinite( lng ) ) {
          const photos: PlacePhoto[] = ( Array.isArray( googlePlace.photos ) ? googlePlace.photos : [] )
            .slice( 0, 8 )
            .map( photo => ( {
              url: photo.getURI?.( { maxWidth: 900, maxHeight: 600 } ) || '',
              attributions: ( Array.isArray( photo.authorAttributions ) ? photo.authorAttributions : [] )
                .map( a => ( { name: String( a.displayName || 'Photo contributor' ), uri: a.uri } ) ),
            } ) )
            .filter( p => Boolean( p.url ) );
          next = {
            name: googlePlace.displayName || r.name,
            addr: googlePlace.formattedAddress || r.addr,
            lat: lat as number,
            lng: lng as number,
            placeId: googlePlace.id,
            photos,
            // Surface only the metadata Google actually returned; absent fields stay
            // undefined so the left card renders no placeholder for them.
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
    // candidate so previewPlace (mapCandidate || place) and the photo overlay follow the
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

  const weatherFreshness = relativeAgeLabel( weather?.currentTime || coreFetchedAt || undefined );
  const airFreshness = relativeAgeLabel( air?.updatedAt || coreFetchedAt || undefined );
  const previewPlace = mapCandidate || place;
  const exactPhotos = hasSelection ? ( previewPlace.photos || [] ) : [];
  const displayPhotos = Array.from(
    new Map( [ ...exactPhotos, ...nearbyPhotos ].map( photo => [ photo.url, photo ] ) ).values(),
  ).slice( 0, 8 );
  const photoPages = displayPhotos.map( photo => [ photo ] );

  useEffect( () => {
    if ( displayPhotos.length < 2 ) return undefined;
    if ( typeof window.matchMedia === 'function' && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) return undefined;
    const id = window.setTimeout( () => {
      const rail = photoRailRef.current;
      if ( !rail || !rail.clientWidth ) return;
      const next = ( photoIndex + 1 ) % displayPhotos.length;
      rail.scrollTo( { left: rail.clientWidth * next, behavior: 'smooth' } );
      setPhotoIndex( next );
    }, 4600 );
    return () => window.clearTimeout( id );
  }, [ displayPhotos.length, photoIndex ] );

  const dotClass = ( sev: Sev ) => `vl-live-dot vl-live-dot-${sev}`;
  const currentPm25 = air?.pollutants.find( p => p.code === 'pm25' ) || null;
  const currentPm25Sev = currentPm25 && Number.isFinite( currentPm25.value )
    ? pm25Severity( currentPm25.value )
    : null;
  const mapActive = Boolean( MAPS_KEY );
  const liveActive = Boolean( MAPS_KEY && hasSelection );
  const bestOutside = bestOutsideWindow( weatherHourly, airForecast );
  const combinedHours = weatherHourly.slice( 0, 24 ).map( ( w, i ) => ( {
    ...w,
    air: airForecast.find( a => Math.abs( a.time - w.time ) < 45 * 60 * 1000 ) || airForecast[ i ],
  } ) );
  const pastRailHours = weatherHistory.slice( -2 ).map( h => ( {
    ...h,
    air: airHistory.find( a => Math.abs( a.time - h.time ) < 45 * 60 * 1000 ),
    railPhase: 'past' as const,
  } ) );
  const futureRailHours = combinedHours.slice( 0, 3 ).map( ( h, i ) => ( {
    ...h,
    railPhase: i === 0 ? 'now' as const : 'future' as const,
  } ) );
  const displayRailHours = [ ...pastRailHours, ...futureRailHours ];

  const historyTemps = weatherHistory.map( h => h.temp ).filter( ( v ): v is number => Number.isFinite( v ) );
  const historyRain = weatherHistory.reduce( ( sum, h ) => sum + ( Number.isFinite( h.rainMm ) ? ( h.rainMm as number ) : 0 ), 0 );
  const oldestTemp = weatherHistory[ 0 ]?.temp;
  const tempDelta = Number.isFinite( weather?.temp ) && Number.isFinite( oldestTemp )
    ? Math.round( ( weather!.temp as number ) - ( oldestTemp as number ) )
    : null;
  const weatherContextParts: string[] = [];
  if ( Number.isFinite( tempDelta ) ) weatherContextParts.push( `${( tempDelta as number ) >= 0 ? '+' : ''}${tempDelta}° vs 24h ago` );
  if ( historyTemps.length ) weatherContextParts.push( `24h range ${Math.min( ...historyTemps )}–${Math.max( ...historyTemps )}°` );
  if ( historyRain > 0 ) weatherContextParts.push( `Rain last 24h ${historyRain.toFixed( 1 )} mm` );
  const weatherContext = weatherContextParts.join( ' · ' );
  const rainSignal = combinedHours.find( h => Number.isFinite( h.rainProb ) && ( h.rainProb as number ) >= 30 ) || null;
  const airDayGroups = new Map<string, AirPoint[]>();
  airForecast.slice( 0, 96 ).forEach( point => {
    const key = new Intl.DateTimeFormat( 'en-IN', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' } ).format( new Date( point.time ) );
    const rows = airDayGroups.get( key ) || [];
    rows.push( point );
    airDayGroups.set( key, rows );
  } );
  const airDayOutlook = Array.from( airDayGroups.values() ).slice( 0, 4 ).map( ( rows, i ) => {
    const aqi = Math.round( rows.reduce( ( sum, row ) => sum + row.aqi, 0 ) / Math.max( 1, rows.length ) );
    return {
      label: i === 0 ? 'Today' : new Intl.DateTimeFormat( 'en-IN', { timeZone: 'Asia/Kolkata', weekday: 'short' } ).format( new Date( rows[ 0 ].time ) ),
      aqi,
      word: aqiCategory( aqi ).word,
    };
  } );

  return (
    <section className="vl-live" aria-labelledby="vl-live-title">
      <span className="vl-live-sr" id="vl-live-title">Live air quality and weather</span>

      <main className="vl-live-shell">
        <div className="vl-live-workspace">
          <section className="vl-live-left" aria-label="Place and environmental details">
            { hasSelection ? (
              <div className="vl-live-place-card" ref={ placeCardRef } tabIndex={ -1 }>
                <div className="vl-live-place-visual">
                  { displayPhotos.length > 0 ? (
                    <>
                      <div
                        className="vl-live-photo-rail"
                        ref={ photoRailRef }
                        aria-label="Place photos"
                        onScroll={ e => {
                          const width = e.currentTarget.clientWidth;
                          if ( width > 0 ) setPhotoIndex( Math.round( e.currentTarget.scrollLeft / width ) );
                        } }
                      >
                        { displayPhotos.map( ( photo, i ) => (
                          <figure className="vl-live-photo-slide" key={ photo.url }>
                            <img
                              className="vl-live-place-image"
                              src={ photo.url }
                              alt={ `${previewPlace.name} photo ${i + 1}` }
                              loading={ i === 0 ? 'eager' : 'lazy' }
                            />
                            { photo.attributions.length > 0 && (
                              <figcaption className="vl-live-photo-credit">
                                { photo.attributions.slice( 0, 2 ).map( ( credit, j ) => (
                                  <React.Fragment key={ `${credit.name}-${j}` }>
                                    { j > 0 ? ' · ' : '' }
                                    { credit.uri ? <a href={ credit.uri } target="_blank" rel="noreferrer">{ credit.name }</a> : credit.name }
                                  </React.Fragment>
                                ) ) }
                              </figcaption>
                            ) }
                          </figure>
                        ) ) }
                      </div>
                      { displayPhotos.length > 1 && (
                        <div className="vl-live-photo-progress" aria-hidden="true">
                          { displayPhotos.map( ( photo, i ) => (
                            <span className={ i === photoIndex ? 'is-active' : '' } key={ photo.url } />
                          ) ) }
                        </div>
                      ) }
                    </>
                  ) : (
                    <div className="vl-live-place-art" aria-hidden="true">
                      <div className="vl-live-art-block vl-live-art-one" />
                      <div className="vl-live-art-block vl-live-art-two" />
                    </div>
                  ) }
                </div>

                <div className="vl-live-place-copy">
                  <h3 className="vl-live-place-name">{ previewPlace.name }</h3>
                  { previewPlace.addr && <p className="vl-live-place-address">{ previewPlace.addr }</p> }
                  { addressDescriptor && <p className="vl-live-descriptor-line">{ addressDescriptor }</p> }
                  { ( previewPlace.primaryType || Number.isFinite( elevationM ) ) && (
                    <>
                      { previewPlace.primaryType && (
                        <div className="vl-live-place-meta">
                          <span className="vl-live-meta-chip">{ previewPlace.primaryType }</span>
                        </div>
                      ) }
                      { Number.isFinite( elevationM ) && (
                        <div className="vl-live-place-facts"><span>Elevation { elevationM } m</span></div>
                      ) }
                    </>
                  ) }
                </div>
              </div>
            ) : null }

            { hasSelection && ( weather || air ) && (
              <section className="vl-live-section">
                <div className="vl-live-section-head">
                  <h3>Now</h3>
                  <span className="vl-live-fresh">{ weatherFreshness.label !== 'Current' ? weatherFreshness.label : airFreshness.label }</span>
                </div>

                <div className="vl-live-now-grid">
                  { weather && (
                    <div className="vl-live-now-cell">
                      <div className="vl-live-now-label">Weather</div>
                      <div className="vl-live-now-main">
                        <strong>{ Number.isFinite( weather.temp ) ? weather.temp : '—' }°</strong>
                        <span>C</span>
                      </div>
                      { weather.condition && <div className="vl-live-now-title">{ weather.condition }</div> }
                      { Number.isFinite( weather.feelsLike ) && <div className="vl-live-now-sub">Feels like { weather.feelsLike }° · current conditions</div> }
                    </div>
                  ) }
                  { air && (
                    <div className="vl-live-now-cell">
                      <div className="vl-live-now-label">Air quality</div>
                      <div className="vl-live-now-main"><strong>{ Math.round( air.aqi ) }</strong><span>AQI</span></div>
                      <div className="vl-live-now-title">{ air.word }</div>
                      { currentPm25 && <div className="vl-live-now-sub">PM2.5 { Math.round( currentPm25.value ) } { currentPm25.unit }</div> }
                    </div>
                  ) }
                </div>

                { weatherContext && <p className="vl-live-now-context">{ weatherContext }</p> }

                { weather && (
                  <div className="vl-live-facts" aria-label="Current conditions">
                    { Number.isFinite( weather.humidity ) && <div className="vl-live-fact"><span>Humidity</span><strong>{ weather.humidity }%</strong></div> }
                    { Number.isFinite( weather.windSpeed ) && <div className="vl-live-fact"><span>Wind</span><strong>{ weather.windSpeed } { weather.windUnit || 'km/h' }</strong></div> }
                    { Number.isFinite( weather.rainProb ) && <div className="vl-live-fact"><span>Rain</span><strong>{ weather.rainProb }%</strong></div> }
                    { Number.isFinite( weather.uv ) && <div className="vl-live-fact"><span>UV</span><strong>{ weather.uv }</strong></div> }
                  </div>
                ) }

                { ( bestOutside || rainSignal ) && (
                  <div className="vl-live-signals">
                    { bestOutside && (
                      <div className="vl-live-signal">
                        <span>Best outside</span>
                        <strong>{ bestOutside.label }</strong>
                        <p>{ bestOutside.note }</p>
                      </div>
                    ) }
                    { rainSignal && (
                      <div className="vl-live-signal vl-live-signal-secondary">
                        <span>Rain likely</span>
                        <strong>{ hourLabel( rainSignal.time ) }</strong>
                        <p>{ rainSignal.rainProb }% chance</p>
                      </div>
                    ) }
                  </div>
                ) }

                { currentPm25 && (
                  <div className="vl-live-air-source-strip" aria-label="Air source comparison">
                    <div>
                      <span>Google model</span>
                      <strong>{ Math.round( currentPm25.value ) } <small>{ currentPm25.unit } PM2.5</small></strong>
                      <small>{ airFreshness.label }</small>
                    </div>
                    <div>
                      <span>Observed</span>
                      <strong>—</strong>
                      <small>No nearby monitor reading</small>
                    </div>
                  </div>
                ) }
              </section>
            ) }

            { displayRailHours.length > 0 && (
              <section className="vl-live-section">
                <div className="vl-live-section-head"><h3>Next 24 hours</h3><span className="vl-live-fresh">Weather + air</span></div>
                <div className="vl-live-forecast-weather" aria-label="Past two hours, now and next two hours">
                  <div className="vl-live-forecast-track">
                    { displayRailHours.map( h => (
                      <article className={ `vl-live-forecast-hour is-${h.railPhase}` } key={ `${h.railPhase}-${h.time}` }>
                        <time>{ h.railPhase === 'now' ? 'Now' : hourLabel( h.time ) }</time>
                        <div className="vl-live-forecast-temp"><strong>{ Number.isFinite( h.temp ) ? h.temp : '—' }°</strong><span>{ Number.isFinite( h.feelsLike ) ? h.feelsLike : '—' }°</span></div>
                        <div className="vl-live-forecast-icon" aria-hidden="true">
                          { h.icon ? <img src={ h.icon + '.svg' } alt="" /> : <span>◐</span> }
                        </div>
                        <div className="vl-live-forecast-wind">
                          <strong>{ Number.isFinite( h.windSpeed ) ? h.windSpeed : '—' }</strong>
                          <span>{ h.windUnit || 'km/h' }</span>
                          <b aria-hidden="true">{ h.windDir || '→' }</b>
                        </div>
                        { h.air && h.railPhase === 'now' && <div className="vl-live-forecast-air">AQI { h.air.aqi }</div> }
                        <div className="vl-live-forecast-rain">{ Number.isFinite( h.rainProb ) ? h.rainProb : 0 }%</div>
                        <div className="vl-live-forecast-node" aria-hidden="true" />
                      </article>
                    ) ) }
                  </div>
                  <div className="vl-live-forecast-baseline" aria-hidden="true"><span className="vl-live-past-line" /><span className="vl-live-future-line" /></div>
                </div>
              </section>
            ) }

            { hasSelection && ( air || weather ) && (
              <section className="vl-live-section">
                <div className="vl-live-tabs" role="tablist" aria-label="Details">
                  <button type="button" role="tab" aria-selected={ detailTab === 'air' } onClick={ () => setDetailTab( 'air' ) }>Air</button>
                  <button type="button" role="tab" aria-selected={ detailTab === 'weather' } onClick={ () => setDetailTab( 'weather' ) }>Weather</button>
                </div>

                { detailTab === 'air' && air && (
                  <>
                    <div className="vl-live-detail-grid" role="tabpanel" aria-label="Air details">
                      { air.pollutants.slice( 0, 4 ).map( p => (
                        <div className="vl-live-metric" key={ p.code }><span>{ p.label }</span><strong>{ Math.round( p.value ) } { p.unit }</strong></div>
                      ) ) }
                    </div>
                    { airDayOutlook.length > 0 && (
                      <div className="vl-live-air-4day" aria-label="Four day air outlook">
                        { airDayOutlook.map( day => (
                          <article className="vl-live-air-day" key={ day.label }><span>{ day.label }</span><strong>AQI { day.aqi }</strong><small>{ day.word }</small></article>
                        ) ) }
                      </div>
                    ) }
                  </>
                ) }

                { detailTab === 'weather' && weather && (
                  <div className="vl-live-detail-grid" role="tabpanel" aria-label="Weather details">
                    { Number.isFinite( weather.feelsLike ) && <div className="vl-live-metric"><span>Feels like</span><strong>{ weather.feelsLike }°C</strong></div> }
                    { Number.isFinite( weather.humidity ) && <div className="vl-live-metric"><span>Humidity</span><strong>{ weather.humidity }%</strong></div> }
                    { Number.isFinite( weather.visibilityKm ) && <div className="vl-live-metric"><span>Visibility</span><strong>{ weather.visibilityKm } km</strong></div> }
                    { Number.isFinite( weather.pressureHpa ) && <div className="vl-live-metric"><span>Pressure</span><strong>{ weather.pressureHpa } hPa</strong></div> }
                  </div>
                ) }
              </section>
            ) }
          </section>

          <section className="vl-live-right" aria-label="Map">
            <div className="vl-live-map-shell">
              { !mapReady && (
                <div className="vl-live-map-fallback" role="status">
                  <span>{ mapFailed ? 'Map temporarily unavailable.' : 'Loading live map…' }</span>
                  { mapFailed && <button type="button" onClick={ () => window.location.reload() }>Retry map</button> }
                </div>
              ) }
              { mapActive && <div className={ `vl-live-map-canvas ${mapReady ? 'is-ready' : ''}` } ref={ mapHost } role="img" aria-label={ hasSelection ? `Map of ${place.name}` : 'Map of India' } /> }

              { mapActive && (
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
                    { searchStatus === 'searching' && <p className="vl-live-search-status" role="status">Searching India…</p> }
                    { searchStatus === 'no-results' && <p className="vl-live-search-status" role="status">Place not found in India.</p> }
                    { searchStatus === 'outside-india' && <p className="vl-live-search-status" role="status">That location is outside India.</p> }
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
          font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:var(--body);background:var(--page);padding-bottom:72px;-webkit-font-smoothing:antialiased;
        }
        .vl-live,.vl-live *{box-sizing:border-box}
        .vl-live button,.vl-live input{font:inherit}
        .vl-live button{cursor:pointer}
        .vl-live button:focus-visible{outline:3px solid var(--green);outline-offset:3px}
        .vl-live input:focus-visible{outline:none}
        .vl-live-sr,.vl-live-sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
        .vl-live-shell{max-width:1320px;margin:0 auto;padding:22px 24px 72px}
        .vl-live-workspace{display:grid;grid-template-columns:minmax(0,.86fr) minmax(0,1.14fr);gap:32px;align-items:stretch}
        .vl-live-left,.vl-live-right{min-width:0}\n        .vl-live-right{display:flex;flex-direction:column}

        .vl-live-place-card{border:1px solid var(--hair);border-radius:14px;background:#fff;overflow:hidden}
        .vl-live-place-visual{position:relative;height:238px;background:var(--alt);overflow:hidden}
        .vl-live-photo-rail{position:absolute;inset:0;display:flex;overflow-x:auto;overflow-y:hidden;scroll-snap-type:x mandatory;scrollbar-width:none;overscroll-behavior-inline:contain;touch-action:pan-x pinch-zoom}
        .vl-live-photo-rail::-webkit-scrollbar{display:none}
        .vl-live-photo-slide{position:relative;flex:0 0 100%;height:100%;margin:0;scroll-snap-align:start;scroll-snap-stop:always;overflow:hidden;background:var(--alt)}
        .vl-live-place-image{display:block;width:100%;height:100%;object-fit:cover;user-select:none}
        .vl-live-photo-progress{position:absolute;z-index:4;left:10px;right:10px;top:10px;display:flex;gap:4px;pointer-events:none}
        .vl-live-photo-progress span{height:3px;flex:1 1 0;border-radius:999px;background:rgba(209,244,112,.42);box-shadow:0 1px 2px rgba(26,58,42,.08)}
        .vl-live-photo-progress span.is-active{background:var(--lime)}
        .vl-live-place-art{position:absolute;inset:28px;display:grid;grid-template-columns:1.1fr .9fr;gap:16px}
        .vl-live-art-block{border:1px solid rgba(26,58,42,.11);border-radius:14px;background:rgba(255,255,255,.78)}
        .vl-live-art-one{transform:translateY(12px)}
        .vl-live-art-two{transform:translateY(-7px);background:rgba(209,244,112,.26)}
        .vl-live-photo-credit{position:absolute;left:9px;right:9px;bottom:8px;z-index:3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin:0;padding:0;background:transparent;text-shadow:0 1px 3px rgba(0,0,0,.82);font-size:8.5px;color:rgba(255,255,255,.94)}
        .vl-live-photo-credit a{color:inherit}
        .vl-live-place-copy{padding:22px 22px 21px}
        .vl-live-place-name{margin:7px 0 0;color:var(--heading);font-size:32px;line-height:1.05;letter-spacing:-1.1px;font-weight:700}
        .vl-live-place-address{margin:8px 0 0;font-size:14px;line-height:1.5;color:var(--muted)}
        .vl-live-descriptor-line{margin:8px 0 0;color:var(--green);font-size:12.5px;line-height:1.45;font-weight:700}
        .vl-live-place-meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}
        .vl-live-meta-chip{display:inline-flex;align-items:center;min-height:30px;padding:0 10px;border:1px solid var(--green);border-radius:var(--pill-r);background:var(--lime-tint);color:var(--green);font-size:11px;font-weight:700}
        .vl-live-place-facts{display:flex;gap:8px;flex-wrap:wrap;margin-top:9px}
        .vl-live-place-facts span{display:inline-flex;align-items:center;min-height:30px;padding:0 10px;border-radius:999px;background:var(--alt);color:var(--muted);font-size:10.5px;font-weight:700}
        .vl-live-empty{padding:22px;border:1px solid var(--hair);border-radius:14px;background:#fff}
        .vl-live-empty span{display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--green)}
        .vl-live-empty strong{display:block;margin-top:8px;font-size:22px;color:var(--heading)}

        .vl-live-section{margin-top:28px;border-top:1px solid var(--hair);padding-top:26px}
        .vl-live-section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:12px}
        .vl-live-section-head h3{margin:0;color:var(--heading);font-size:21px;line-height:1.27;letter-spacing:-.45px}
        .vl-live-fresh{font-size:11px;color:var(--muted)}
        .vl-live-now-grid{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--hair);border-radius:14px;overflow:hidden;background:#fff}
        .vl-live-now-cell{padding:18px 19px 17px}
        .vl-live-now-cell+.vl-live-now-cell{border-left:1px solid var(--hair)}
        .vl-live-now-label{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--green)}
        .vl-live-now-main{display:flex;align-items:flex-end;gap:10px;margin-top:12px}
        .vl-live-now-main strong{color:var(--heading);font-size:40px;line-height:.9;letter-spacing:-1.4px}
        .vl-live-now-main span{padding-bottom:3px;font-size:14px;font-weight:700;color:var(--muted)}
        .vl-live-now-title{margin-top:10px;font-size:14.5px;font-weight:700;color:var(--heading)}
        .vl-live-now-sub{margin-top:5px;font-size:12px;color:var(--muted);line-height:1.4}
        .vl-live-now-context{margin:10px 2px 0;color:var(--muted);font-size:11.5px;line-height:1.45}
        .vl-live-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));margin-top:12px;border:1px solid var(--hair);border-radius:14px;overflow:hidden}
        .vl-live-fact{padding:12px 8px;text-align:center;background:#fff}
        .vl-live-fact+.vl-live-fact{border-left:1px solid var(--hair)}
        .vl-live-fact span{display:block;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
        .vl-live-fact strong{display:block;margin-top:6px;font-size:12.5px;color:var(--heading)}
        .vl-live-signals{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}
        .vl-live-signal{padding:12px 13px;border:1px solid rgba(209,244,112,.95);border-radius:14px;background:var(--lime-tint)}
        .vl-live-signal-secondary{background:#fff;border-color:var(--hair)}
        .vl-live-signal span{display:block;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--green)}
        .vl-live-signal strong{display:block;margin-top:5px;font-size:15px;color:var(--heading)}
        .vl-live-signal p{margin:5px 0 0;font-size:11.5px;line-height:1.45;color:var(--status)}
        .vl-live-air-source-strip{display:grid;grid-template-columns:1fr 1fr;margin-top:12px;border:1px solid var(--hair);border-radius:14px;overflow:hidden;background:#fff}
        .vl-live-air-source-strip>div{padding:12px 13px}
        .vl-live-air-source-strip>div+div{border-left:1px solid var(--hair)}
        .vl-live-air-source-strip span{display:block;color:var(--muted);font-size:9.5px;font-weight:800;text-transform:uppercase;letter-spacing:.055em}
        .vl-live-air-source-strip strong{display:block;margin-top:6px;color:var(--heading);font-size:18px;letter-spacing:-.025em}
        .vl-live-air-source-strip strong small{font-size:10px;color:var(--muted);font-weight:650;letter-spacing:0}
        .vl-live-air-source-strip>div>small{display:block;margin-top:4px;color:var(--muted);font-size:10px;line-height:1.35}

        .vl-live-forecast-weather{--fw-surface:#f8faef;position:relative;overflow:hidden;border-radius:20px;background:var(--fw-surface);color:var(--green);padding:10px 10px 20px;border:1px solid rgba(26,58,42,.12)}
        .vl-live-forecast-track{display:grid;grid-template-columns:repeat(5,minmax(108px,1fr));overflow-x:auto;scrollbar-width:none;scroll-snap-type:x proximity}
        .vl-live-forecast-track::-webkit-scrollbar{display:none}
        .vl-live-forecast-hour{position:relative;min-height:310px;padding:15px 10px 44px;display:flex;flex-direction:column;align-items:center;gap:14px;border-radius:16px;color:rgba(26,58,42,.66);scroll-snap-align:start}
        .vl-live-forecast-hour.is-now{background:rgba(209,244,112,.58);color:var(--green)}
        .vl-live-forecast-hour time{font-size:13px;font-weight:700}
        .vl-live-forecast-temp{display:flex;align-items:baseline;gap:5px}
        .vl-live-forecast-temp strong{font-size:29px;line-height:1;letter-spacing:-.035em;color:var(--green)}
        .vl-live-forecast-temp span{font-size:14px;color:rgba(26,58,42,.52)}
        .vl-live-forecast-icon{width:58px;height:58px;border-radius:50%;display:grid;place-items:center;background:var(--green);font-size:28px;color:var(--lime);overflow:hidden}
        .vl-live-forecast-icon img{width:44px;height:44px;filter:saturate(.7)}
        .vl-live-forecast-wind{display:grid;grid-template-columns:auto auto auto;align-items:center;gap:4px;font-size:11px}
        .vl-live-forecast-wind strong{font-size:14px;color:var(--green)}
        .vl-live-forecast-wind span{color:rgba(26,58,42,.56)}
        .vl-live-forecast-wind b{font-size:13px;color:rgba(26,58,42,.46)}
        .vl-live-forecast-air{min-height:22px;padding:4px 7px;border:1px solid rgba(26,58,42,.12);border-radius:999px;background:rgba(255,255,255,.68);font-size:9.5px;font-weight:750;color:var(--green)}
        .vl-live-forecast-rain{margin-top:auto;font-size:15px;font-weight:750;color:var(--green)}
        .vl-live-forecast-node{position:absolute;left:50%;bottom:15px;width:10px;height:10px;transform:translateX(-50%);border-radius:50%;background:var(--fw-surface);border:3px solid rgba(26,58,42,.58);z-index:2}
        .vl-live-forecast-hour.is-now .vl-live-forecast-node{background:var(--green);border-color:var(--green)}
        .vl-live-forecast-baseline{pointer-events:none;position:absolute;left:7%;right:7%;bottom:28px;height:1px}
        .vl-live-past-line{position:absolute;left:0;width:50%;top:0;border-top:2px dashed rgba(26,58,42,.30)}
        .vl-live-future-line{position:absolute;left:50%;right:0;top:0;border-top:2px solid rgba(26,58,42,.42)}

        .vl-live-tabs{display:grid;grid-template-columns:1fr 1fr;gap:4px;max-width:330px;padding:3px;border:1px solid var(--hair);border-radius:var(--pill-r);background:#fff}
        .vl-live-tabs button{min-height:38px;border:0;border-radius:var(--pill-r);background:transparent;color:var(--green);font-size:12px;font-weight:700}
        .vl-live-tabs button[aria-selected="true"]{background:rgba(209,244,112,.60)}
        .vl-live-detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin-top:14px;border:1px solid var(--hair);border-radius:14px;overflow:hidden}
        .vl-live-metric{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:13px 14px;background:#fff;border-bottom:1px solid var(--hair)}
        .vl-live-metric:nth-child(odd){border-right:1px solid var(--hair)}
        .vl-live-metric:nth-last-child(-n+2){border-bottom:0}
        .vl-live-metric span{font-size:12px;color:var(--muted)}
        .vl-live-metric strong{font-size:13px;color:var(--heading);text-align:right}
        .vl-live-air-4day{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:13px}
        .vl-live-air-day{border:1px solid var(--hair);border-radius:12px;padding:9px;background:#fff}
        .vl-live-air-day span{display:block;color:var(--muted);font-size:10px;font-weight:700}
        .vl-live-air-day strong{display:block;margin-top:5px;color:var(--heading);font-size:13px}
        .vl-live-air-day small{display:block;margin-top:3px;color:var(--green);font-size:10px;font-weight:700}

        .vl-live-map-shell{position:relative;height:100%;min-height:748px;border:1px solid var(--hair);border-radius:14px;overflow:hidden;background:#eef1ed;isolation:isolate}
        .vl-live-map-canvas{position:absolute;inset:0;width:100%;height:100%;opacity:0}
        .vl-live-map-canvas.is-ready{opacity:1}
        .vl-live-map-fallback{position:absolute;inset:0;display:grid;place-items:center;z-index:0;background:#eef1ed;color:var(--green);font-size:13px}
        .vl-live-map-fallback button{margin-left:8px;border:1px solid var(--green);border-radius:999px;background:#fff;color:var(--green);padding:7px 11px}
        .vl-live-map-search{position:absolute;z-index:10;top:16px;left:50%;transform:translateX(-50%);width:min(430px,calc(100% - 190px))}
        .vl-live-search{position:relative}
        .vl-live-search-field{height:50px;display:flex;align-items:center;gap:10px;padding:0 17px;border:1px solid rgba(26,58,42,.28);border-radius:var(--pill-r);background:#fff;box-shadow:0 5px 18px rgba(26,58,42,.08)}
        .vl-live-search-field:focus-within{border-color:rgba(26,58,42,.48);box-shadow:0 0 0 3px rgba(26,58,42,.12),0 5px 18px rgba(26,58,42,.08)}
        .vl-live-search-field svg{width:19px;height:19px;stroke:var(--green);fill:none;stroke-width:2;flex:0 0 auto}
        .vl-live-search-field input{width:100%;border:0;outline:0;background:transparent;color:var(--heading);font-size:14px}
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
          .vl-live-workspace{grid-template-columns:1fr}
          .vl-live-right{order:-1}
          .vl-live-map-shell{height:620px}
        }
        @media(max-width:700px){
          .vl-live-shell{padding:10px 10px 44px}
          .vl-live-map-shell{height:46dvh;min-height:430px;max-height:560px}
          .vl-live-map-search{top:10px;width:calc(100% - 20px)}
          .vl-live-layers{top:70px;right:10px}
          .vl-live-selected-label{bottom:22px;width:calc(100% - 20px);max-width:none}
          .vl-live-place-visual{height:188px}
          .vl-live-place-copy{padding:18px}
          .vl-live-place-name{font-size:27px}
          .vl-live-now-grid{grid-template-columns:1fr}
          .vl-live-now-cell+.vl-live-now-cell{border-left:0;border-top:1px solid var(--hair)}
          .vl-live-facts{grid-template-columns:repeat(2,minmax(0,1fr))}
          .vl-live-fact:nth-child(3){border-left:0;border-top:1px solid var(--hair)}
          .vl-live-fact:nth-child(4){border-top:1px solid var(--hair)}
          .vl-live-signals{grid-template-columns:1fr}
          .vl-live-air-source-strip{grid-template-columns:1fr}
          .vl-live-air-source-strip>div+div{border-left:0;border-top:1px solid var(--hair)}
          .vl-live-forecast-weather{border-radius:17px;padding-inline:8px}
          .vl-live-forecast-track{grid-template-columns:repeat(5,126px)}
          .vl-live-forecast-hour{min-height:288px}
          .vl-live-detail-grid{grid-template-columns:1fr}
          .vl-live-metric:nth-child(odd){border-right:0}
          .vl-live-metric:nth-last-child(-n+2){border-bottom:1px solid var(--hair)}
          .vl-live-metric:last-child{border-bottom:0}
          .vl-live-air-4day{grid-template-columns:repeat(2,minmax(0,1fr))}
        }
        @media(max-height:500px) and (orientation:landscape){
          .vl-live-shell{padding-top:8px}
          .vl-live-map-shell{height:calc(100dvh - 24px);min-height:250px}
          .vl-live-search-field{height:44px}
          .vl-live-layers{top:64px}
        }
        @media(prefers-reduced-motion:reduce){
          .vl-live *{scroll-behavior:auto!important;transition:none!important}
        }
      `}</style>
    </section>
  );
};

export default VayuLokLive;