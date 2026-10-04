import React, { useCallback, useEffect, useRef, useState } from 'react';
import BlogContribution from './BlogContribution';
import ShareLinks from './ShareLinks';
import { SITE_ORIGIN } from '../config/share';

/**
 * VayuLok LIVE content, appended BELOW the rotating-word hero on /vayulok/.
 *
 * WHAT THIS IS. The REAL, live-wired version of docs/mocks/vayulok-live-mock.html.
 * The mock is a VISUAL reference only: its layout and styled-jsx design tokens are
 * ported verbatim here, but every static sample value is replaced with LIVE data
 * fetched CLIENT-SIDE from Google's India-SKU APIs plus the Maps JavaScript API.
 *
 * THE MOCK'S "never call these from a browser" STANCE IS A MOCK CONSTRAINT, NOT THIS
 * PAGE'S. The mock header says weather/air/solar/pollen are server-side web services
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

// FINAL TARGET: the AQI / PM2.5 map layer is a deck.gl ScatterplotLayer of REAL sampled
// air-quality points (see RESEARCH-deckgl-sampling-architecture.md), rendered over the
// Google roadmap through GoogleMapsOverlay. The old raster air-quality layer-tile overlay is gone.
// Lime #d1f470 is reserved for the AQI|PM2.5 selector chrome; the dots use the
// VayuLok no-red severity ramp (--aqi-good -> --aqi-worst) converted to RGBA below.

// VayuLok NO-RED severity palette as RGBA, keyed by Sev. These are the EXACT hex tokens the
// --aqi-* CSS custom properties use (good #1a3a2a / sat #3da35a / mod #d1f470 (lime) /
// poor #e8c547 / worst #c98a2e), converted to [r,g,b,a] for the deck.gl ScatterplotLayer.
// Google's UAQI_RED_GREEN tile palette is deliberately NOT inherited - no red anywhere.
const DOT_FILL_RGBA: Record<Sev, [ number, number, number, number ]> = {
  good: [ 26, 58, 42, 210 ],
  sat: [ 61, 163, 90, 210 ],
  mod: [ 209, 244, 112, 210 ],
  poor: [ 232, 197, 71, 210 ],
  worst: [ 201, 138, 46, 210 ],
};
// Dark-green outline (--green #1a3a2a) so dots read against light roads.
const DOT_LINE_RGBA: [ number, number, number, number ] = [ 26, 58, 42, 230 ];

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
] as const;

/* The shape of a resolved google.maps.places.Place once fetchFields has run. Mirrors the
   Places JS API: every metadata field is optional and only present when Google returned
   it. We never fabricate; absence simply means that line does not render. */
interface GooglePlaceLike {
  fetchFields?: ( req: { fields: string[] } ) => Promise<void>;
  displayName?: string;
  formattedAddress?: string;
  location?: { lat?: () => number; lng?: () => number };
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
  // Camera-only neutral India starting point. This is never rendered as a selected
  // destination; hasSelection stays false until search or an explicit valid map click.
  name: 'India',
  addr: '',
  lat: 22.9734,
  lng: 78.6569,
  photos: [],
};

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
interface SolarState {
  maxPanels?: number;
  roofAreaM2?: number;
  yearlyKwh?: number;
  sunshineHrs?: number;
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
  if ( Number.isFinite( temp ) ) out.temp = Math.round( temp );
  if ( Number.isFinite( feels ) ) out.feelsLike = Math.round( feels );
  if ( Number.isFinite( rain ) ) out.rainProb = Math.round( rain );
  if ( Number.isFinite( rainMm ) ) out.rainMm = rainMm;
  if ( Number.isFinite( storm ) ) out.stormProb = Math.round( storm );
  if ( Number.isFinite( uv ) ) out.uv = Math.round( uv );
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
  // `place` always contains map coordinates, but it is not a visitor-selected
  // destination until hasSelection becomes true. This keeps the initial India camera neutral.
  const [ place, setPlace ] = useState<PlaceState>( DEFAULT_PLACE );
  const [ hasSelection, setHasSelection ] = useState( false );
  const [ detailTab, setDetailTab ] = useState<'air' | 'weather'>( 'air' );
  const [ mapReady, setMapReady ] = useState( false );
  const [ mapFailed, setMapFailed ] = useState( false );
  const [ photoIndex, setPhotoIndex ] = useState( 0 );
  const [ searchStatus, setSearchStatus ] = useState<'idle' | 'searching' | 'no-results' | 'unavailable'>( 'idle' );
  const [ solarRequested, setSolarRequested ] = useState( false );
  const [ solarLoading, setSolarLoading ] = useState( false );

  const [ air, setAir ] = useState<AirState | null>( null );
  const [ weather, setWeather ] = useState<WeatherState | null>( null );
  const [ solar, setSolar ] = useState<SolarState | null>( null );
  const [ pollen, setPollen ] = useState<PollenRow[] | null>( null );
  const [ weatherHourly, setWeatherHourly ] = useState<WeatherHour[]>( [] );
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
  // FEAT-004: the Google-Destinations-style bottom bar. destGeometryRef holds any building
  // outline polygon + entrance markers drawn by the SearchDestinations enhancement so they
  // can be cleared when the place changes / on unmount; destAbortRef aborts an in-flight
  // destination-resolution lookup. These are ONLY populated when SearchDestinations is
  // feature-detected in the loaded Maps JS build (not in sandbox / referrer-restricted keys),
  // so the sandbox/degraded path leaves them null and draws no geometry.
  const destGeometryRef = useRef<{ polygon?: unknown; entrances?: unknown[] }>( {} );
  const destAbortRef = useRef<AbortController | null>( null );

  useEffect( () => {
    setSolar( null );
    setSolarRequested( false );
    setSolarLoading( false );
    setPhotoIndex( 0 );
    setMapCandidate( null );
    setNearbyPhotos( [] );
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
        zoom: 5,
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

      if ( maps.Marker ) {
        markerRef.current = new maps.Marker( {
          position: { lat: DEFAULT_PLACE.lat, lng: DEFAULT_PLACE.lng },
          map: null,
          title: '',
          icon: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" width="34" height="42" viewBox="0 0 34 42"><path d="M17 1C8.2 1 1 8.2 1 17c0 11.1 16 24 16 24s16-12.9 16-24C33 8.2 25.8 1 17 1Z" fill="%23d1f470" stroke="%231a3a2a" stroke-width="2"/><circle cx="17" cy="17" r="5.5" fill="%231a3a2a"/></svg>',
          ),
        } );
      }

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
        gc?.geocode?.( { location: { lat, lng }, region: 'in' }, async ( rows, status ) => {
          if ( status !== 'OK' || !Array.isArray( rows ) || !rows.length ) return;
          const typedRows = rows as Array<{
            formatted_address?: string;
            place_id?: string;
            address_components?: Array<{ short_name?: string; types?: string[] }>;
          }>;
          const first = typedRows.find( row => row.address_components?.some(
            component => component.types?.includes( 'country' ) && component.short_name === 'IN',
          ) );
          if ( !first ) {
            setSearchStatus( 'no-results' );
            return;
          }
          const next: PlaceState = {
            name: first.formatted_address?.split( ',' )[ 0 ] || 'Selected location',
            addr: first.formatted_address || '',
            lat,
            lng,
            photos: [],
          };
          setHasSelection( true );
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
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent( MAPS_KEY )}&libraries=places&loading=async`;
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
    const exactPhotos = target.photos || [];
    if ( exactPhotos.length ) {
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
     the place changes AND a key is present. Solar is deliberately user-triggered because
     Building Insights is the comparatively expensive SKU. Each call is independently guarded,
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

    // POLLEN - forecast:lookup, one day. Degrade silently if absent.
    const fetchPollen = async () => {
      try {
        const res = await fetch(
          `https://pollen.googleapis.com/v1/forecast:lookup?key=${encodeURIComponent( MAPS_KEY )}&location.latitude=${lat}&location.longitude=${lng}&days=5`,
          { signal: ac.signal },
        );
        if ( !res.ok ) return;
        const d = await res.json();
        const daily = Array.isArray( d?.dailyInfo ) ? d.dailyInfo : [];
        const rows: PollenRow[] = [];
        daily.forEach( ( day: any, dayIndex: number ) => {
          const date = day?.date;
          const dateObj = date?.year && date?.month && date?.day
            ? new Date( Date.UTC( date.year, date.month - 1, date.day ) )
            : null;
          const dayLabel = dayIndex === 0
            ? 'Today'
            : dateObj
              ? new Intl.DateTimeFormat( 'en-IN', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' } ).format( dateObj )
              : 'Day ' + String( dayIndex + 1 );
          const types: { code?: string; displayName?: string; indexInfo?: { value?: number } }[] = day?.pollenTypeInfo || [];
          types.forEach( t => {
            const v = t.indexInfo?.value;
            if ( t.displayName && Number.isFinite( v ) ) {
              rows.push( { label: t.displayName, index: v as number, word: pollenCategory( v as number ), day: dayLabel } );
            }
          } );
        } );
        if ( rows.length ) store.pollen = rows;
      } catch { /* silent degradation */ }
    };

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

    const loadAlerts = async () => {
      const url = 'https://weather.googleapis.com/v1/publicAlerts:lookup?key=' + encodeURIComponent( MAPS_KEY )
        + '&location.latitude=' + lat + '&location.longitude=' + lng + '&languageCode=en';
      const data = await getJson( url );
      if ( !data || ac.signal.aborted ) return;
      const rows: WeatherAlertRow[] = ( Array.isArray( data.weatherAlerts ) ? data.weatherAlerts : [] ).slice( 0, 3 ).map( ( a: any, i: number ) => ( {
        id: String( a?.alertId || a?.eventType || 'weather-alert-' + i ),
        title: String( a?.alertTitle?.text || a?.description || a?.eventType || 'Weather alert' ),
        description: typeof a?.description === 'string' ? a.description : undefined,
        area: typeof a?.areaName === 'string' ? a.areaName : undefined,
        severity: typeof a?.severity === 'string' ? a.severity.replaceAll( '_', ' ' ) : undefined,
        urgency: typeof a?.urgency === 'string' ? a.urgency.replaceAll( '_', ' ' ) : undefined,
        expires: typeof a?.expirationTime === 'string' ? a.expirationTime : undefined,
      } ) );
      forecastStore.alerts = rows;
      setWeatherAlerts( rows );
    };

    const loadAirForecast = async () => {
      const start = new Date();
      start.setUTCMinutes( 0, 0, 0 );
      start.setUTCHours( start.getUTCHours() + 1 );
      const end = new Date( start.getTime() + 24 * 60 * 60 * 1000 );
      const res = await fetch(
        'https://airquality.googleapis.com/v1/forecast:lookup?key=' + encodeURIComponent( MAPS_KEY ),
        {
          method: 'POST',
          signal: ac.signal,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( {
            location: { latitude: lat, longitude: lng },
            period: { startTime: start.toISOString(), endTime: end.toISOString() },
            pageSize: 24,
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

  const loadSolar = useCallback( async () => {
    if ( !MAPS_KEY || !hasSelection || solarLoading ) return;
    setSolarRequested( true );
    setSolarLoading( true );
    try {
      const res = await fetch(
        `https://solar.googleapis.com/v1/buildingInsights:findClosest?key=${encodeURIComponent( MAPS_KEY )}&location.latitude=${place.lat}&location.longitude=${place.lng}`,
      );
      if ( !res.ok ) { setSolar( null ); return; }
      const d = await res.json();
      const sp = d?.solarPotential;
      if ( !sp ) { setSolar( null ); return; }
      const out: SolarState = {};
      if ( Number.isFinite( sp.maxArrayPanelsCount ) ) out.maxPanels = sp.maxArrayPanelsCount;
      if ( Number.isFinite( sp.maxArrayAreaMeters2 ) ) out.roofAreaM2 = Math.round( sp.maxArrayAreaMeters2 );
      if ( Number.isFinite( sp.maxSunshineHoursPerYear ) ) out.sunshineHrs = Math.round( sp.maxSunshineHoursPerYear );
      const cfg = Array.isArray( sp.solarPanelConfigs ) ? sp.solarPanelConfigs[ sp.solarPanelConfigs.length - 1 ] : null;
      if ( cfg && Number.isFinite( cfg.yearlyEnergyDcKwh ) ) out.yearlyKwh = Math.round( cfg.yearlyEnergyDcKwh );
      setSolar( Object.keys( out ).length ? out : null );
    } catch {
      setSolar( null );
    } finally {
      setSolarLoading( false );
    }
  }, [ place.lat, place.lng, solarLoading, hasSelection ] );

  /* ---------------------------------------------------------------------------------
     RECENTRE the map + move the marker when the place changes (after the map exists). */
  useEffect( () => {
    const w = window as unknown as { google?: { maps?: { LatLng: new ( a: number, b: number ) => unknown } } };
    const map = mapRef.current as { setCenter?: ( p: { lat: number; lng: number } ) => void; setZoom?: ( zoom: number ) => void } | null;
    const marker = markerRef.current as {
      setPosition?: ( p: { lat: number; lng: number } ) => void;
      setTitle?: ( t: string ) => void;
      setMap?: ( m: unknown ) => void;
    } | null;
    if ( !map || !marker || !w.google?.maps ) return;
    if ( !hasSelection ) {
      marker.setMap?.( null );
      return;
    }
    map.setCenter?.( { lat: place.lat, lng: place.lng } );
    map.setZoom?.( 14 );
    marker.setMap?.( map );
    marker.setPosition?.( { lat: place.lat, lng: place.lng } );
    marker.setTitle?.( place.name );
  }, [ place, mapReady, hasSelection ] );

  /* ---------------------------------------------------------------------------------
     DESTINATION BAR GEOMETRY CLEANUP.
     SearchDestinations is a Geocoding API v4 web service, not a Maps JS importLibrary
     capability. The Google-style destination bar remains; the invalid importLibrary('search')
     experiment is intentionally removed rather than faking a browser-only integration. */
  useEffect( () => {
    const geo = destGeometryRef.current;
    ( geo.polygon as { setMap?: ( m: unknown ) => void } | undefined )?.setMap?.( null );
    ( geo.entrances || [] ).forEach( e => ( e as { setMap?: ( m: unknown ) => void } ).setMap?.( null ) );
    destGeometryRef.current = {};
    destAbortRef.current?.abort();
    destAbortRef.current = null;
  }, [ place ] );

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
        const mapped: SearchResult[] = rows.slice( 0, 6 ).map( ( row: unknown ) => {
          const pr = row as { formatted_address?: string; geometry?: { location?: { lat: () => number; lng: () => number } } };
          const loc = pr.geometry?.location;
          const place: PlaceState = {
            name: pr.formatted_address?.split( ',' )[ 0 ] || 'Place',
            addr: pr.formatted_address || '',
            lat: loc ? loc.lat() : DEFAULT_PLACE.lat,
            lng: loc ? loc.lng() : DEFAULT_PLACE.lng,
            photos: [],
          };
          return { name: place.name, addr: place.addr, place };
        } );
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
        await googlePlace.fetchFields?.( { fields: [ 'displayName', 'formattedAddress', 'location', 'photos', ...PLACE_META_FIELDS ] } );
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

  /* LEFT-CARD metadata/attributes/description/supporting-info, derived from data already
     in state. Each list is built ONLY from values genuinely present on the selected
     place or the already-fetched live context, so the card renders real facts or nothing
     - never a placeholder or an invented attribute. */
  const placeMeta: { label: string; value: string }[] = [];
  if ( previewPlace.primaryType ) placeMeta.push( { label: 'Category', value: previewPlace.primaryType } );
  if ( Number.isFinite( previewPlace.rating ) ) {
    placeMeta.push( {
      label: 'Rating',
      value: Number.isFinite( previewPlace.userRatingCount )
        ? `${previewPlace.rating!.toFixed( 1 )} (${previewPlace.userRatingCount!.toLocaleString( 'en-IN' )} reviews)`
        : previewPlace.rating!.toFixed( 1 ),
    } );
  }

  const placeAttributes: string[] = [];
  if ( previewPlace.websiteURI ) placeAttributes.push( 'Official website listed' );
  if ( Array.isArray( previewPlace.types ) ) {
    for ( const t of previewPlace.types ) {
      if ( t && t !== previewPlace.primaryType && !placeAttributes.includes( t ) ) placeAttributes.push( t );
    }
  }

  // Supporting information: honest, place-specific context already fetched elsewhere. The
  // full air/weather result still lives in the NOW block / layer result, so we surface
  // only compact one-liners here (band word, weather condition, precise coordinates).
  const supportingInfo: string[] = [];
  if ( liveActive && air ) supportingInfo.push( `Air quality band: ${air.word}` );
  if ( liveActive && weather?.condition ) supportingInfo.push( `Current weather: ${weather.condition}` );
  if ( liveActive && Number.isFinite( previewPlace.lat ) && Number.isFinite( previewPlace.lng ) ) {
    supportingInfo.push( `Coordinates: ${previewPlace.lat.toFixed( 4 )}, ${previewPlace.lng.toFixed( 4 )}` );
  }

  return (
    <section className="vl-live" aria-labelledby="vl-live-title">
      <h2 className="vl-live-sr" id="vl-live-title">Live air quality and weather</h2>

      <div className="vl-live-wrap vl-live-grid">
        {/* ===== LEFT COLUMN: selected-place card first, then all content, stacked =====
            FINAL TARGET: the LEFT column leads with the selected-place card (photo + lime
            number pill + place name + address), and, when a air-quality layer is active, the
            existing VayuLok air-quality RESULT system renders inside this card. All markup
            stays INLINE in the return so styled-jsx keeps its vl-live- scope. */}
        <div className="vl-live-left">

          {/* SELECTED-PLACE CARD. The photo + number pill moved OFF the map into this card
              (FINAL TARGET: the gallery no longer floats on the map). The place name and
              full address always render here - they are known without a key, so this is a
              sensible lead, not a misleading placeholder. Google Place Photo author
              attributions (.vl-live-photo-credit + contributor <a>) ride WITH the photo in
              this new location, as the Maps Platform ToS and the req-06 guard require. */}
          { hasSelection ? (
          <div className="vl-live-block vl-live-block-top">
            <div className="vl-live-place-card" ref={ placeCardRef } tabIndex={ -1 }>
              { displayPhotos.length > 0 && (
                <div className="vl-live-photo-shell">
                  {/* Number-only pill (req 01): referee SVG + bare number (e.g. "8"),
                      never "8 photos". Pill background is exactly the site lime #d1f470. */}
                  <div className="vl-live-photo-count" aria-label={ `${displayPhotos.length} place photos` }>
                    <svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#1f1f1f" aria-hidden="true"><path d="M240-280v-120H120v-80h120v-120h80v120h120v80H320v120h-80Zm390 80v-438l-92 66-46-70 164-118h64v560h-90Z"/></svg>
                    <span>{ displayPhotos.length }</span>
                  </div>
                  <div
                    ref={ photoRailRef }
                    className="vl-live-place-photos"
                    aria-label={ `Photos near ${previewPlace.name}` }
                    onScroll={ e => {
                      const el = e.currentTarget;
                      if ( el.clientWidth ) setPhotoIndex( Math.max( 0, Math.min( photoPages.length - 1, Math.round( el.scrollLeft / el.clientWidth ) ) ) );
                    } }
                  >
                    { photoPages.map( ( page, pageIndex ) => (
                      <div className="vl-live-photo-page" key={ page.map( p => p.url ).join( '|' ) }>
                        { page.map( ( photo, i ) => (
                          <figure className={ `vl-live-place-photo ${i === 0 ? 'is-primary' : 'is-secondary'}`.trim() } key={ photo.url }>
                            <img
                              src={ photo.url }
                              alt={ `${previewPlace.name} area ${pageIndex * 3 + i + 1}` }
                              loading={ pageIndex === 0 && i === 0 ? 'eager' : 'lazy' }
                            />
                            { photo.attributions.length > 0 && (
                              <figcaption className="vl-live-photo-credit">
                                { photo.attributions.slice( 0, 2 ).map( ( credit, creditIndex ) => (
                                  <React.Fragment key={ `${credit.name}-${creditIndex}` }>
                                    { creditIndex > 0 ? ' · ' : '' }
                                    { credit.uri
                                      ? <a href={ credit.uri } target="_blank" rel="noreferrer">{ credit.name }</a>
                                      : credit.name }
                                  </React.Fragment>
                                ) ) }
                              </figcaption>
                            ) }
                          </figure>
                        ) ) }
                      </div>
                    ) ) }
                  </div>
                  { photoPages.length > 1 && (
                    <div className="vl-live-photo-tabs" role="tablist" aria-label={ `Photo set ${photoIndex + 1} of ${photoPages.length}` }>
                      { photoPages.map( ( _, i ) => (
                        <span
                          key={ i }
                          className="vl-live-photo-tab"
                          role="tab"
                          tabIndex={ 0 }
                          aria-selected={ i === photoIndex }
                          aria-label={ `Show photo set ${i + 1}` }
                          onClick={ () => {
                            const el = photoRailRef.current;
                            if ( el ) el.scrollTo( { left: el.clientWidth * i, behavior: 'smooth' } );
                            setPhotoIndex( i );
                          } }
                          onKeyDown={ e => {
                            if ( e.key !== 'Enter' && e.key !== ' ' ) return;
                            e.preventDefault();
                            const el = photoRailRef.current;
                            if ( el ) el.scrollTo( { left: el.clientWidth * i, behavior: 'smooth' } );
                            setPhotoIndex( i );
                          } }
                        />
                      ) ) }
                    </div>
                  ) }
                </div>
              ) }

              <div className="vl-live-place-body">
                <p className="vl-live-place" id="vl-live-now-place">{ place.name }</p>
                <p className="vl-live-place-addr">{ place.addr }</p>

                {/* REAL PLACE METADATA / ATTRIBUTES / DESCRIPTION (FINAL TARGET default
                    state). Every line is gated on a datum Google actually returned for the
                    selected place - we never fabricate an attribute or show a placeholder.
                    With no key nothing is fetched, so none of these render. Supporting-info
                    bullets below are composed from already-fetched live context that
                    genuinely pertains to THIS place (AQI band, weather, coordinates) and
                    never duplicate the full air/weather result that lives in the NOW block
                    and the layer-gated result. */}
                { ( placeMeta.length > 0 || placeAttributes.length > 0 || previewPlace.summary || supportingInfo.length > 0 ) && (
                  <div className="vl-live-place-meta">
                    { placeMeta.length > 0 && (
                      <dl className="vl-live-place-facts">
                        { placeMeta.map( fact => (
                          <div className="vl-live-place-fact" key={ fact.label }>
                            <dt>{ fact.label }</dt>
                            <dd>{ fact.value }</dd>
                          </div>
                        ) ) }
                      </dl>
                    ) }

                    { placeAttributes.length > 0 && (
                      <ul className="vl-live-place-attrs">
                        { placeAttributes.map( attr => (
                          <li key={ attr }>
                            <svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="#1a3a2a" aria-hidden="true"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg>
                            <span>{ attr }</span>
                          </li>
                        ) ) }
                      </ul>
                    ) }

                    { previewPlace.summary && (
                      <p className="vl-live-place-desc">{ previewPlace.summary }</p>
                    ) }

                    { supportingInfo.length > 0 && (
                      <ul className="vl-live-place-support">
                        { supportingInfo.map( info => (
                          <li key={ info }>{ info }</li>
                        ) ) }
                      </ul>
                    ) }
                  </div>
                ) }

                {/* ENVIRONMENTAL RESULT - reuses the EXISTING VayuLok air-quality result
                    markup/styles. Shown INSIDE the left card only when a air-quality layer is
                    active. AQI leads with the AQI value/category/dominant pollutant; PM2.5
                    leads with the PM2.5 reading. Both reuse the same severity dot, category
                    pill, pollutant rows and health guidance already defined on this page. */}
                { liveActive && layer && air && (
                  <div className="vl-live-layer-result" aria-labelledby="vl-live-layer-result-title">
                    <p className="vl-live-eyebrow" id="vl-live-layer-result-title">
                      { layer === 'PM25' ? 'PM2.5 layer result' : 'Air quality now' }
                    </p>

                    { layer === 'AQI' && (
                      <>
                        <div className="vl-live-figure">
                          <span className={ dotClass( air.sev ) } aria-hidden="true" />
                          <span className="vl-live-metric-xl">{ air.aqi }</span>
                          <span className="vl-live-cat">{ air.word }</span>
                        </div>
                        { air.pollutants.filter( p => p.code === 'pm25' ).map( p => (
                          <p className="vl-live-sub-fact" key="layer-pm25">PM2.5 { Math.round( p.value ) } { p.unit }</p>
                        ) ) }
                        { air.dominant && <p className="vl-live-cond">Dominant pollutant { air.dominant }.</p> }
                      </>
                    ) }

                    { layer === 'PM25' && currentPm25 && currentPm25Sev && (
                      <>
                        <div className="vl-live-figure">
                          <span className={ dotClass( currentPm25Sev ) } aria-hidden="true" />
                          <span className="vl-live-metric-xl">{ Math.round( currentPm25.value ) }</span>
                          <span className="vl-live-cat">{ currentPm25.unit }</span>
                        </div>
                        <p className="vl-live-label vl-live-status-label">PM2.5 status</p>
                        <p className="vl-live-status-word">{ statusWord( currentPm25Sev ) }</p>
                        <p className="vl-live-sub-fact">AQI context: { air.aqi } · { air.word }</p>
                        { air.dominant && <p className="vl-live-cond">Dominant pollutant { air.dominant }.</p> }
                      </>
                    ) }

                    {/* Heatmap scale - reuses the existing no-red --aqi-* ramp, both ends
                        labelled in WORDS so colour is never the sole carrier of meaning. */}
                    <div className="vl-live-scale-legend" role="img" aria-label={ `${layer === 'PM25' ? 'PM2.5' : 'Air quality'} air-quality scale from good to hazardous` }>
                      <div className="vl-live-scale" aria-hidden="true" />
                      <div className="vl-live-scale-ends">
                        <span>{ layer === 'PM25' ? 'Lower' : 'Good' }</span>
                        <span>{ layer === 'PM25' ? 'Higher' : 'Severe' }</span>
                      </div>
                    </div>

                    { air.advisory && <p className="vl-live-body vl-live-layer-advisory">{ air.advisory }</p> }
                  </div>
                ) }
              </div>
            </div>
          </div>
          ) : (
            <div className="vl-live-block vl-live-block-top vl-live-empty-selection">
              <p className="vl-live-eyebrow">Choose a place</p>
              <h3 className="vl-live-h2">Search India to see live weather and air.</h3>
              <p className="vl-live-body">The map starts neutral. Weather, air quality, photos and forecasts load only after you select a place.</p>
            </div>
          ) }

          {/* FEAT-002: a lightweight loading / error affordance for the layer-activated grid
              + center air fetch. The full air RESULT now lives in the left-card
              layer-result block above; the former NOW/forecast/weather/pollen sections are
              retired because selecting a place no longer fetches weather/pollen/forecast. */}
          { liveActive && layer && ( dataLoading || coreError ) && (
            <div className="vl-live-block">
              { dataLoading && !coreError && (
                <div className="vl-live-data-skeleton" role="status" aria-label="Loading air quality">
                  <i /><i /><i /><i />
                </div>
              ) }
              { coreError && !dataLoading && (
                <div className="vl-live-data-error" role="status">
                  <span>Air quality is temporarily unavailable for this area.</span>
                  <button type="button" onClick={ () => setRefreshNonce( v => v + 1 ) }>Retry</button>
                </div>
              ) }
            </div>
          ) }

          { hasSelection && ( weather || air ) && (
            <div className="vl-live-block vl-live-now-compact">
              <div className="vl-live-forecast-head">
                <div>
                  <p className="vl-live-eyebrow">Current conditions</p>
                  <h3 className="vl-live-h2">Now</h3>
                </div>
                <time>{ weatherFreshness.label }</time>
              </div>

              <div className="vl-live-now-split">
                { weather && (
                  <div className="vl-live-now-pane">
                    <p className="vl-live-label">Weather</p>
                    <div className="vl-live-now-main">
                      <strong>{ Number.isFinite( weather.temp ) ? weather.temp + '°' : '—' }</strong>
                      <span>{ weather.condition || 'Current conditions' }</span>
                    </div>
                    { Number.isFinite( weather.feelsLike ) && <p className="vl-live-sub-fact">Feels like { weather.feelsLike }°</p> }
                  </div>
                ) }
                { air && (
                  <div className="vl-live-now-pane">
                    <p className="vl-live-label">Air quality</p>
                    <div className="vl-live-now-main">
                      <strong>AQI { air.aqi }</strong>
                      <span>{ air.word }</span>
                    </div>
                    { currentPm25 && <p className="vl-live-sub-fact">PM2.5 { Math.round( currentPm25.value ) } { currentPm25.unit }</p> }
                  </div>
                ) }
              </div>

              { weather && (
                <div className="vl-live-now-facts" aria-label="Current weather facts">
                  { Number.isFinite( weather.humidity ) && <div><span>Humidity</span><strong>{ weather.humidity }%</strong></div> }
                  { Number.isFinite( weather.windSpeed ) && <div><span>Wind</span><strong>{ weather.windSpeed } { weather.windUnit || 'km/h' }</strong></div> }
                  { weather.windDir && <div><span>Direction</span><strong>{ weather.windDir }</strong></div> }
                  { Number.isFinite( weather.rainProb ) && <div><span>Rain chance</span><strong>{ weather.rainProb }%</strong></div> }
                  { Number.isFinite( weather.rainMm ) && <div><span>Rainfall</span><strong>{ weather.rainMm } mm</strong></div> }
                  { Number.isFinite( weather.uv ) && <div><span>UV</span><strong>{ weather.uv }</strong></div> }
                </div>
              ) }

              { air?.advisory && (
                <div className="vl-live-health-compact">
                  <p className="vl-live-label">Health guidance</p>
                  <p>{ air.advisory }</p>
                </div>
              ) }

              { bestOutside && (
                <div className="vl-live-best-compact">
                  <p className="vl-live-label">Best outside</p>
                  <strong>{ bestOutside.label }</strong>
                  <span>{ bestOutside.note }</span>
                </div>
              ) }
            </div>
          ) }

          { combinedHours.length > 0 && (
            <div className="vl-live-block">
              <div className="vl-live-forecast-head">
                <div>
                  <p className="vl-live-eyebrow">Today</p>
                  <h3 className="vl-live-h2">Next 24 hours</h3>
                </div>
                <time>{ new Intl.DateTimeFormat( 'en-IN', { timeZone: 'Asia/Kolkata', month: 'short', day: 'numeric' } ).format( new Date() ) }</time>
              </div>
              <div className="vl-live-hour-rail vl-live-hour-rail-primary" aria-label="Next 24 hours weather and air quality">
                { combinedHours.map( ( h, i ) => (
                  <article className="vl-live-hour-card" key={ h.time }>
                    <time>{ hourLabel( h.time ) }</time>
                    { h.icon && <img src={ h.icon + '.svg' } alt="" loading="lazy" /> }
                    <strong>{ Number.isFinite( h.temp ) ? h.temp + '°' : '—' }</strong>
                    <span>{ Number.isFinite( h.rainProb ) ? h.rainProb + '% rain' : h.condition || 'Forecast' }</span>
                    <span>{ h.air ? 'AQI ' + h.air.aqi : 'AQI —' }</span>
                    { i === 0 && <em>Now</em> }
                  </article>
                ) ) }
              </div>
            </div>
          ) }

          { hasSelection && ( air || weather ) && (
            <section className="vl-live-section vl-live-detail-switcher" aria-labelledby="vl-live-detail-title">
              <div className="vl-live-detail-head">
                <h3 className="vl-live-h2" id="vl-live-detail-title">Details</h3>
                <div className="vl-live-detail-tabs" role="tablist" aria-label="Environmental details">
                  <button type="button" role="tab" aria-selected={ detailTab === 'air' } onClick={ () => setDetailTab( 'air' ) }>Air</button>
                  <button type="button" role="tab" aria-selected={ detailTab === 'weather' } onClick={ () => setDetailTab( 'weather' ) }>Weather</button>
                </div>
              </div>

              { detailTab === 'air' && air && (
                <div role="tabpanel" aria-label="Air details">
                  <div className="vl-live-detail-list">
                    { air.pollutants.map( p => (
                      <div key={ p.code }>
                        <span>{ p.label }</span>
                        <strong>{ Math.round( p.value ) } { p.unit }</strong>
                      </div>
                    ) ) }
                  </div>

                  { airForecast.length > 0 && (
                    <>
                      <h4 className="vl-live-minor-title">AQ forecast</h4>
                      <div className="vl-live-hour-rail" aria-label="Air quality forecast">
                        { airForecast.filter( ( _, i ) => i % 3 === 0 ).map( p => (
                          <article className="vl-live-hour-card vl-live-hour-card-air" key={ p.time }>
                            <time>{ hourLabel( p.time ) }</time>
                            <strong>AQI { p.aqi }</strong>
                            <span>{ p.word }</span>
                            { Number.isFinite( p.pm25 ) && <span>PM2.5 { Math.round( p.pm25! ) }</span> }
                          </article>
                        ) ) }
                      </div>
                    </>
                  ) }

                  <div className="vl-live-history-head">
                    <h4 className="vl-live-minor-title">Past air quality</h4>
                    <div className="vl-live-history-controls" role="group" aria-label="Air quality history range">
                      { ( [ [ 24, '24h' ], [ 168, '7d' ], [ 720, '30d' ] ] as const ).map( ( [ hours, label ] ) => (
                        <button type="button" key={ hours } aria-pressed={ historyRange === hours } onClick={ () => setHistoryRange( hours ) }>{ label }</button>
                      ) ) }
                    </div>
                  </div>
                  { historyLoading ? (
                    <p className="vl-live-small">Loading history…</p>
                  ) : airHistory.length > 0 ? (
                    <div className="vl-live-history" aria-label={ 'AQI history for ' + historyRange + ' hours' }>
                      { airHistory.filter( ( _, i ) => {
                        const step = Math.max( 1, Math.ceil( airHistory.length / 72 ) );
                        return i % step === 0 || i === airHistory.length - 1;
                      } ).map( p => (
                        <i key={ p.time } style={ { height: Math.max( 8, Math.min( 100, p.aqi / 5 ) ) + '%' } } title={ hourLabel( p.time ) + ' · AQI ' + p.aqi } />
                      ) ) }
                    </div>
                  ) : (
                    <p className="vl-live-small">Air history is not available for this location right now.</p>
                  ) }
                </div>
              ) }

              { detailTab === 'weather' && weather && (
                <div role="tabpanel" aria-label="Weather details">
                  <div className="vl-live-weather-grid">
                    { [
                      [ 'Feels like', Number.isFinite( weather.feelsLike ) ? weather.feelsLike + '°' : null ],
                      [ 'Humidity', Number.isFinite( weather.humidity ) ? weather.humidity + '%' : null ],
                      [ 'Wind speed', Number.isFinite( weather.windSpeed ) ? weather.windSpeed + ' ' + ( weather.windUnit || 'km/h' ) : null ],
                      [ 'Wind direction', weather.windDir || null ],
                      [ 'Rainfall', Number.isFinite( weather.rainMm ) ? weather.rainMm + ' mm' : null ],
                      [ 'Rain chance', Number.isFinite( weather.rainProb ) ? weather.rainProb + '%' : null ],
                      [ 'Visibility', Number.isFinite( weather.visibilityKm ) ? weather.visibilityKm + ' km' : null ],
                      [ 'UV index', Number.isFinite( weather.uv ) ? String( weather.uv ) : null ],
                      [ 'Dew point', Number.isFinite( weather.dewPoint ) ? weather.dewPoint + '°' : null ],
                      [ 'Pressure', Number.isFinite( weather.pressureHpa ) ? weather.pressureHpa + ' hPa' : null ],
                      [ 'Cloud cover', Number.isFinite( weather.cloudCover ) ? weather.cloudCover + '%' : null ],
                      [ 'Gust', Number.isFinite( weather.windGust ) ? weather.windGust + ' km/h' : null ],
                    ].filter( row => row[ 1 ] !== null ).map( row => (
                      <div key={ String( row[ 0 ] ) }><p className="vl-live-label">{ row[ 0 ] }</p><strong>{ row[ 1 ] }</strong></div>
                    ) ) }
                  </div>

                  { weatherDaily.length > 0 && (
                    <>
                      <div className="vl-live-sunline">
                        <div><p className="vl-live-label">Sunrise</p><strong>{ weatherDaily[ 0 ].sunrise ? new Intl.DateTimeFormat( 'en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit' } ).format( new Date( weatherDaily[ 0 ].sunrise! ) ) : '—' }</strong></div>
                        <div><p className="vl-live-label">Sunset</p><strong>{ weatherDaily[ 0 ].sunset ? new Intl.DateTimeFormat( 'en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit' } ).format( new Date( weatherDaily[ 0 ].sunset! ) ) : '—' }</strong></div>
                      </div>
                      <h4 className="vl-live-minor-title">10-day outlook</h4>
                      <div className="vl-live-day-rail" aria-label="10-day weather outlook">
                        { weatherDaily.map( d => (
                          <article className="vl-live-day-card" key={ d.time }>
                            <strong>{ d.label }</strong>
                            <span>{ d.dateLabel }</span>
                            { d.icon && <img src={ d.icon + '.svg' } alt="" loading="lazy" /> }
                            <b>{ Number.isFinite( d.max ) ? d.max + '°' : '—' } / { Number.isFinite( d.min ) ? d.min + '°' : '—' }</b>
                            <span>{ Number.isFinite( d.rainProb ) ? d.rainProb + '% rain' : d.condition || 'Forecast' }</span>
                          </article>
                        ) ) }
                      </div>
                    </>
                  ) }

                  { weatherAlerts.length > 0 && (
                    <div className="vl-live-alerts">
                      <h4 className="vl-live-minor-title">Weather alerts</h4>
                      { weatherAlerts.map( alert => (
                        <article className="vl-live-alert" key={ alert.id }>
                          <strong>{ alert.title }</strong>
                          { alert.description && <p>{ alert.description }</p> }
                          <span>{ [ alert.area, alert.severity, alert.urgency, alert.expires ? 'Until ' + new Intl.DateTimeFormat( 'en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit' } ).format( new Date( alert.expires ) ) : '' ].filter( Boolean ).join( ' · ' ) }</span>
                        </article>
                      ) ) }
                    </div>
                  ) }
                </div>
              ) }
            </section>
          ) }

          {/* SOLAR - expensive relative to Weather/Air, so load only after explicit user action. */}
          { hasSelection && (
            <section className="vl-live-section" aria-labelledby="vl-live-solar-title">
            <h3 className="vl-live-h2" id="vl-live-solar-title">Solar &ndash; Building Insights</h3>
            { !solarRequested && (
              <>
                <p className="vl-live-small vl-live-mb16">Rooftop solar potential is loaded only when you ask for it.</p>
                <button className="vl-live-solar-load" type="button" onClick={ () => void loadSolar() }>View solar potential</button>
              </>
            ) }
            { solarLoading && <p className="vl-live-small">Loading rooftop potential…</p> }
            { solarRequested && !solarLoading && !solar && <p className="vl-live-small">Solar building insights are not available for this location.</p> }
            { solar && ( Number.isFinite( solar.maxPanels ) || Number.isFinite( solar.roofAreaM2 ) || Number.isFinite( solar.yearlyKwh ) || Number.isFinite( solar.sunshineHrs ) ) && (
              <>
              <p className="vl-live-small vl-live-mb16">Rooftop solar potential for this address, from the Solar API&rsquo;s building insights.</p>
              { Number.isFinite( solar.maxPanels ) && (
                <div className="vl-live-prow"><p className="vl-live-label">Max panels</p><span className="vl-live-track"><span className="vl-live-bar vl-live-bar-mod" style={ { width: '62%' } } /></span><span className="vl-live-metric-md">{ solar.maxPanels } panels</span><span className="vl-live-prow-cat">Rooftop</span></div>
              ) }
              { Number.isFinite( solar.sunshineHrs ) && (
                <div className="vl-live-prow"><p className="vl-live-label">Sunshine</p><span className="vl-live-track"><span className="vl-live-bar vl-live-bar-poor" style={ { width: '78%' } } /></span><span className="vl-live-metric-md">{ solar.sunshineHrs!.toLocaleString( 'en-IN' ) } hrs/yr</span><span className="vl-live-prow-cat">Per year</span></div>
              ) }
              { Number.isFinite( solar.roofAreaM2 ) && (
                <div className="vl-live-prow"><p className="vl-live-label">Roof area</p><span className="vl-live-track"><span className="vl-live-bar vl-live-bar-sat" style={ { width: '48%' } } /></span><span className="vl-live-metric-md">{ solar.roofAreaM2 } m²</span><span className="vl-live-prow-cat">Usable</span></div>
              ) }
              { Number.isFinite( solar.yearlyKwh ) && (
                <div className="vl-live-prow"><p className="vl-live-label">Yearly energy</p><span className="vl-live-track"><span className="vl-live-bar vl-live-bar-poor" style={ { width: '71%' } } /></span><span className="vl-live-metric-md">{ solar.yearlyKwh!.toLocaleString( 'en-IN' ) } kWh</span><span className="vl-live-prow-cat">Estimated</span></div>
              ) }
              </>
            ) }
            </section>
          ) }

          {/* POLLEN - section renders only when the forecast returned types. */}
          { pollen && pollen.length > 0 && (
            <section className="vl-live-section" aria-labelledby="vl-live-pollen-title">
              <h3 className="vl-live-h2" id="vl-live-pollen-title">Pollen</h3>
              <p className="vl-live-small vl-live-mb16">Up to five days of pollen conditions, when Google Pollen has coverage for the selected place.</p>
              <div className="vl-live-pollen-grid">
                { pollen.map( ( row, i ) => (
                  <article className="vl-live-pollen-card" key={ row.day + '-' + row.label + '-' + i }>
                    <p className="vl-live-label">{ row.day }</p>
                    <strong>{ row.label }</strong>
                    <span>Index { row.index } · { row.word }</span>
                  </article>
                ) ) }
              </div>
            </section>
          ) }

          {/* SUBSCRIBE - the shipped WhatsApp anchor, verbatim URL from the user instruction. */}
          <section className="vl-live-section" aria-label="Subscribe on WhatsApp">
            <a
              className="vl-live-wa-subscribe"
              href="https://wa.me/message/BEA3HNW3LNM3A1"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Subscribe on WhatsApp"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" width="20" height="20">
                <path fill="currentColor" d="M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.46-2.4-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.61-.91-2.21-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.8.37-.27.3-1.03 1.02-1.03 2.48 0 1.46 1.06 2.87 1.21 3.07.15.2 2.1 3.2 5.08 4.49.71.3 1.26.49 1.69.62.71.23 1.36.2 1.87.12.57-.09 1.76-.72 2-1.41.25-.7.25-1.29.18-1.42-.08-.12-.28-.2-.57-.35M12.05 21.79h-.01a9.87 9.87 0 01-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 01-1.51-5.26C2.16 6.45 6.6 2.01 12.05 2.01c2.64 0 5.12 1.03 6.99 2.9a9.83 9.83 0 012.89 6.99c0 5.45-4.44 9.89-9.88 9.89M20.46 3.49A11.82 11.82 0 0012.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.3-1.65a11.88 11.88 0 005.69 1.45c6.55 0 11.89-5.34 11.89-11.89 0-3.18-1.24-6.17-3.48-8.42z" />
              </svg>
              <span>Subscribe on WhatsApp</span>
            </a>
          </section>

          {/* CONTRIBUTE - reuse the shipped component and its shared central preset config:
              ₹100 / ₹250 / ₹500, with no separate custom amount path. */}
          <section className="vl-live-section">
            <BlogContribution postId="vayulok" slug="vayulok" embedded />
          </section>

          {/* SHARE - reuse the shipped component with the canonical /vayulok/ url. */}
          <section className="vl-live-section">
            <ShareLinks url={ `${SITE_ORIGIN}/vayulok/` } title="VayuLok — Bharat air and weather intelligence" />
          </section>
        </div>

        {/* ===== RIGHT COLUMN: resilient map =====
            The keyed Maps JS canvas is the enhanced path. A keyless Google Maps embed
            sits underneath it until mapReady becomes true, so a rejected/delayed
            browser key can never leave visitors staring at a blank grey panel. */}
        <div className="vl-live-right">
          <div className="vl-live-map-sticky">
            <div className="vl-live-map-stage">
              { !mapReady && (
                <div
                  className="vl-live-map-fallback"
                  role="status"
                  aria-label={ mapFailed ? 'Map unavailable' : hasSelection ? `Loading map of ${place.name}` : 'Loading map of India' }
                >
                  <span className="vl-live-map-fallback-pin" aria-hidden="true" />
                  <div className="vl-live-map-fallback-copy">
                    <p className="vl-live-map-fallback-place">{ hasSelection ? place.name : 'India' }</p>
                    <p className="vl-live-map-fallback-status">{ mapFailed ? 'Map temporarily unavailable.' : 'Loading live map…' }</p>
                    { mapFailed && (
                      <button className="vl-live-map-retry" type="button" onClick={ () => window.location.reload() }>Retry map</button>
                    ) }
                  </div>
                </div>
              ) }
              { mapActive && (
                <div
                  className={ `vl-live-map-canvas ${mapReady ? 'is-ready' : ''}`.trim() }
                  ref={ mapHost }
                  role="img"
                  aria-label={ hasSelection ? `Map of ${place.name}` : 'Map of India' }
                />
              ) }

              { mapActive && (
                <div className="vl-live-map-search">
                  <label className="vl-live-sr-only" htmlFor="vl-live-search">Search a city or place</label>
                  <div className="vl-live-search">
                    <div className="vl-live-search-field">
                      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                        <circle cx="9" cy="9" r="6.25" stroke="#1a3a2a" strokeWidth="2" />
                        <path d="M13.8 13.8 L18.5 18.5" stroke="#1a3a2a" strokeWidth="2" strokeLinecap="round" />
                      </svg>
                      <input
                        className="vl-live-search-input"
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
                          setResults( recent );
                          setActive( recent.length ? 0 : -1 );
                          setOpen( recent.length > 0 );
                          setSearchStatus( 'idle' );
                        } }
                        onKeyDown={ onKeyDown }
                      />
                    </div>
                    <ul
                      className="vl-live-search-results"
                      id="vl-live-search-results"
                      role="listbox"
                      aria-label="Matching places"
                      hidden={ !open || !results.length }
                    >
                      { results.map( ( r, i ) => (
                        <li
                          key={ `${r.name}-${r.addr}-${i}` }
                          className="vl-live-search-option"
                          role="option"
                          aria-selected={ i === active }
                          onMouseDown={ e => { e.preventDefault(); void choose( r ); } }
                        >
                          <span className="vl-live-search-option-name">{ r.name }</span>
                          { r.addr && <span className="vl-live-search-option-addr">{ r.addr }</span> }
                        </li>
                      ) ) }
                    </ul>
                    { searchStatus === 'searching' && <p className="vl-live-search-status" role="status">Searching India…</p> }
                    { searchStatus === 'no-results' && <p className="vl-live-search-status" role="status">Place not found in India.</p> }
                    { searchStatus === 'unavailable' && (
                      <p className="vl-live-search-status vl-live-search-status-error" role="status">
                        Place search is temporarily unavailable. <button type="button" onClick={ () => { if ( query.trim() ) void runSearch( query ); } }>Retry</button>
                      </p>
                    ) }
                  </div>
                </div>
              ) }

              {/* AQI | PM2.5 air-quality selector. The ONLY controls remaining on the map
                  (FINAL TARGET: no Expand/Collapse, no photo gallery, no on-map place
                  card). Selecting a layer both toggles the map air-quality layer AND swaps the
                  LEFT-card result content. The active tab is filled with the EXACT site
                  lime #d1f470 (--lime) with #1a3a2a text. Controls appear only once the
                  Maps JS canvas exists, so a fallback map never implies a toggleable layer.
                  Kept INLINE so styled-jsx keeps its scope; inset from the bottom corners
                  so Google's logo/legal stays visible. */}
              { mapReady && (
                <div className="vl-live-map-controls" role="group" aria-label="Air quality layers">
                  <button
                    className="vl-live-layer"
                    type="button"
                    disabled={ !hasSelection }
                    aria-pressed={ layer === 'AQI' }
                    onClick={ () => setLayer( v => v === 'AQI' ? null : 'AQI' ) }
                  >AQI</button>
                  <button
                    className="vl-live-layer"
                    type="button"
                    disabled={ !hasSelection }
                    aria-pressed={ layer === 'PM25' }
                    onClick={ () => setLayer( v => v === 'PM25' ? null : 'PM25' ) }
                  >PM2.5</button>
                </div>
              ) }

              {/* FEAT-004 - Google-Destinations-style BOTTOM SELECTED-PLACE BAR (like
                  https://mapsplatform.google.com/demos/destinations/). Renders only when
                  live (a Maps key exists) AND a place name is in state. It is a real
                  keyboard-focusable button: clicking it RE-CENTERS the map on the
                  destination (setCenter + marker) - it NEVER fetches air/weather/pollen
                  (those stay gated on the AQI/PM2.5 pill). Shows the destination NAME
                  (uppercased in CSS) + a middle-dot + the location/type (previewPlace
                  .primaryType when Google returned it, else the formatted address) + a
                  trailing chevron. Never fabricates a type/location: name + addr are
                  always present, primaryType only when Google actually returned it.
                  Kept INLINE so styled-jsx keeps its vl-live- scope. The CSS insets it
                  from the bottom-left (Google logo) and bottom-right (.gm-style-cc legal)
                  corners so the mandated attribution stays visible. */}
              { liveActive && previewPlace.name && (
                <button
                  type="button"
                  className="vl-live-map-destbar"
                  aria-label={ `${previewPlace.name}, ${previewPlace.primaryType || previewPlace.addr || ''}`.trim().replace( /,\s*$/, '' ) }
                  onClick={ () => {
                    const card = placeCardRef.current;
                    if ( !card ) return;
                    card.scrollIntoView( { behavior: 'smooth', block: 'start' } );
                    window.setTimeout( () => card.focus( { preventScroll: true } ), 250 );
                  } }
                >
                  <span className="vl-live-map-destbar-text">
                    <span className="vl-live-map-destbar-name">{ previewPlace.name }</span>
                    { ( previewPlace.primaryType || previewPlace.addr ) && (
                      <>
                        <span className="vl-live-map-destbar-sep" aria-hidden="true">·</span>
                        <span className="vl-live-map-destbar-meta">{ previewPlace.primaryType || previewPlace.addr }</span>
                      </>
                    ) }
                  </span>
                  <span className="vl-live-map-destbar-chevron" aria-hidden="true">›</span>
                </button>
              ) }
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        /* vl-live- prefixed, scoped under this component root. The custom properties live
           on .vl-live rather than :root. No reset, no html/body/* rule, no bare element
           selector. Design tokens are ported from docs/mocks/vayulok-live-mock.html. */
        .vl-live{
          font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          color:#1a1a1a;-webkit-font-smoothing:antialiased;background:#fff;padding-bottom:72px;

          --paper:#fff;--ground:#fafafa;
          --lime:#d1f470;--lime-tint:rgba(209,244,112,.22);
          --green:#1a3a2a;--green-dot:#3da35a;--hair:#e5e7eb;
          --ink-head:rgba(0,0,0,.95);--ink-body:rgba(0,0,0,.898);--ink-strong:#000;
          --ink-base:#1a1a1a;--ink-muted:rgba(0,0,0,.54);--ink-status:rgba(0,0,0,.7);--ink-second:rgba(0,0,0,.66);

          /* AQI severity ramp - NO red: dark green -> lime -> amber. The Satisfactory
             rung is #3da35a (the home .home-mark-dot green, same as --green-dot), not the
             darker #4b8058: the owner's "too much dark green" note moved it to the lighter
             traceable value so the ramp and the 24h history read as mid-tones, not a block
             of near-black green. See .agents/tasks/vayulok-home-aligned-mock/design-tokens.md. */
          --aqi-good:#1a3a2a;--aqi-sat:#3da35a;--aqi-mod:#d1f470;--aqi-poor:#e8c547;--aqi-worst:#c98a2e;
          --tint-warn:#fdf4e3;

          --r-panel:14px;--r-field:10px;--r-pill:999px;--r-btn:13px;
          --e-glide:cubic-bezier(.16,1,.3,1);--e-draw:cubic-bezier(.22,.61,.36,1);
        }
        .vl-live,.vl-live *{box-sizing:border-box}
        .vl-live [hidden]{display:none !important}

        .vl-live-wrap{width:100%;max-width:1300px;margin:0 auto;padding:0 24px}
        .vl-live-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;font-size:40px;font-weight:700;line-height:1.08;letter-spacing:-1.2px}
        /* In VayuLok, Contribute is a full section, so its h2 uses the Home section rung rather
           than BlogContribution's quiet eyebrow treatment. Scoped here so blog-post embeds keep
           their intentionally quieter hierarchy. */
        .vl-live :global(.bc-title){font-size:40px;font-weight:700;line-height:1.08;letter-spacing:-1.2px;text-transform:none;color:rgba(0,0,0,.95);margin:0 0 14px}

        /* Type ladder MEASURED from the live home page (wecare.digital): Inter,
           text #1a1a1a; h2 40px/700/-1.2px; eyebrow 12px/700/0.72px-tracking
           uppercase in dark green #1a3a2a (NOT the light --green, which read as
           loose/washed-out against the home language); body a tighter 17px. */
        .vl-live-h2{margin:0 0 14px;font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;letter-spacing:-1.2px;color:rgba(0,0,0,.95)}
        .vl-live-card-h{margin:0 0 6px;font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;color:#1a1a1a}
        .vl-live-body{margin:0;max-width:62ch;font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.898)}
        .vl-live-eyebrow{margin:0 0 12px;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#1a3a2a}
        .vl-live-label{margin:0 0 7px;font-size:12px;font-weight:600;letter-spacing:.01em;color:rgba(0,0,0,.54)}
        .vl-live-small{margin:0;font-size:13px;line-height:1.4;color:var(--ink-muted)}
        .vl-live-mb16{margin-bottom:16px}

        .vl-live-block{padding-block:48px}
        .vl-live-block:first-child{padding-top:0}
        .vl-live-block-top{padding-top:0}

        /* The grid. ONE grid, TWO columns, TWO items. */
        .vl-live-grid{display:grid;grid-template-columns:minmax(0,1fr);row-gap:64px;padding-top:48px}
        .vl-live-left{min-width:0;container-type:inline-size;container-name:vllive}
        .vl-live-right{min-width:0}

        .vl-live-left > .vl-live-section{margin-top:64px;padding-top:0;border-top:0}

        .vl-live-map-sticky{display:flex;flex-direction:column;gap:10px}
        /* 03A - the whole map surface reads as ONE rounded panel. The stage owns the
           14px home panel radius (per design-tokens.md); the canvas and fallback inherit
           it so no square corner shows through at any zoom. */
        .vl-live-map-stage{position:relative;height:340px;overflow:hidden;border:1px solid var(--hair);border-radius:14px;background:var(--ground);box-shadow:none}
        .vl-live-map-fallback{
          position:absolute;inset:0;z-index:0;display:flex;align-items:center;justify-content:center;gap:14px;
          width:100%;height:100%;padding:24px;border:0;border-radius:inherit;overflow:hidden;
          background-color:#eef3ef;
          background-image:
            linear-gradient(rgba(26,58,42,.055) 1px,transparent 1px),
            linear-gradient(90deg,rgba(26,58,42,.055) 1px,transparent 1px),
            radial-gradient(circle at 22% 24%,rgba(209,244,112,.55),transparent 24%),
            radial-gradient(circle at 78% 72%,rgba(26,58,42,.08),transparent 28%);
          background-size:36px 36px,36px 36px,100% 100%,100% 100%;
        }
        .vl-live-map-fallback-pin{width:18px;height:18px;flex:0 0 18px;border:5px solid var(--green);border-radius:50% 50% 50% 0;background:var(--lime);transform:rotate(-45deg);box-shadow:0 4px 12px rgba(26,58,42,.18)}
        .vl-live-map-fallback-copy{position:relative;z-index:1}
        .vl-live-map-fallback-place{margin:0;font-size:16px;font-weight:700;line-height:1.25;color:var(--green)}
        .vl-live-map-fallback-status{margin:3px 0 0;font-size:13px;line-height:1.35;color:var(--ink-muted)}
        .vl-live-map-canvas{position:absolute;inset:0;z-index:2;opacity:0;pointer-events:none;border-radius:inherit;overflow:hidden;background:transparent}

        /* FEAT-002: the AQI/PM2.5 layer is a deck.gl ScatterplotLayer of REAL sampled points,
           drawn in the map's WebGL context by GoogleMapsOverlay - it adds no covering DOM, so
           the dots never sit over Google's logo/legal. Lime #d1f470 is reserved for the
           AQI|PM2.5 selector chrome; the dots use the no-red --aqi-* ramp (converted to RGBA in
           JS). No rule anywhere targets .gm-style-cc, a[href*="google"] or img[alt="Google"], so
           Google's logo/legal and the Place Photo author attributions stay intact (ToS). */

        .vl-live-map-retry{min-height:44px;margin-top:10px;padding:0 18px;border:2px solid #1a3a2a;border-radius:999px;background:#fff;color:#1a3a2a;font:inherit;font-size:14px;font-weight:600;cursor:pointer}        .vl-live-map-canvas.is-ready{opacity:1;pointer-events:auto}

        @media(min-width:1024px){
          /* Two equal columns with a fixed gap so they cannot overlap. The earlier
             track definition summed past the container width once the gap was added,
             so the right map column slid over the left content. */
          .vl-live-grid{grid-template-columns:minmax(0,.72fr) minmax(0,1.08fr);column-gap:36px;row-gap:0}
          .vl-live-map-sticky{position:sticky;top:96px;height:calc(100vh - 120px)}
          .vl-live-map-stage{flex:1 1 auto;min-height:0;height:auto}
        }

        /* The asymmetric band - stacks in a narrow column, two-up above 620px. */
        .vl-live-band{display:grid;grid-template-columns:minmax(0,1fr);gap:28px;align-items:start}
        .vl-live-band-aside{min-width:0;padding-top:28px;border-top:1px solid var(--hair)}
        @container vllive (min-width:620px){
          .vl-live-band{grid-template-columns:minmax(0,1fr) 380px;gap:44px}
          .vl-live-band-aside{padding-top:0;border-top:0;padding-left:44px;border-left:1px solid var(--hair)}
        }

        /* Search. 03B - horizontally centred over the map with clear space above it,
           max-width so it never spans edge-to-edge, and the highest overlay z-index so
           the field (and its results dropdown anchored directly beneath) sits above the
           canvas and the layer/photo overlays. The field keeps its 2px #1a3a2a outer
           border + lime focus ring (defined on .vl-live-search-field below). */
        .vl-live-map-search{position:absolute;top:18px;left:50%;transform:translateX(-50%);z-index:7;width:min(380px,calc(100% - 32px))}
        .vl-live-search{position:relative;width:100%;max-width:380px}
        .vl-live-sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
        /* One control, matching the shipped BlogSearch field: a single bordered box
           (2px rgba(26,58,42,.22), 12px radius, 52px) that darkens its border and
           shows a lime ring on focus. The field owns the ONLY border and the ONLY
           focus ring; the input inside is fully neutralised below. */
        .vl-live-search-field{display:flex;align-items:center;gap:10px;min-height:52px;padding:0 18px;border:2px solid #1a3a2a;border-radius:999px;background:rgba(255,255,255,.92);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-shadow:none}
        .vl-live-search-field:focus-within{border-color:#1a3a2a;outline:3px solid #1a3a2a;outline-offset:2px;box-shadow:0 4px 12px rgba(26,58,42,.10)}
        /* The input is neutralised against the site's GLOBAL input:focus rules
           (inner-pages.css / Dashboard.css), which were drawing a second rounded
           box (lime box-shadow + 8px radius + padding) INSIDE this field - the
           "inner border" the owner reported. Zero every box-defining property with
           !important so no global rule can reintroduce an inner box. */
        .vl-live-search-input{flex:1 1 auto;min-width:0;height:auto;font:inherit;font-size:17px;color:rgba(0,0,0,.898);background:transparent !important;border:0 !important;outline:0 !important;box-shadow:none !important;border-radius:0 !important;padding:0 !important}
        .vl-live-search-input:focus,.vl-live-search-input:focus-visible{box-shadow:none !important;border:0 !important;outline:0 !important}
        .vl-live-search-input::placeholder{color:rgba(0,0,0,.44)}
        .vl-live-search-results{position:absolute;top:calc(100% + 6px);inset-inline:0;z-index:5;margin:0;padding:0;list-style:none;overflow:hidden;border:1px solid var(--hair);border-radius:var(--r-field);background:var(--paper)}
        .vl-live-search-option{display:block;min-height:52px;padding:10px 14px;cursor:pointer}
        .vl-live-search-option + .vl-live-search-option{border-top:1px solid var(--hair)}
        .vl-live-search-option[aria-selected="true"]{background:var(--lime)}
        .vl-live-search-option-name{display:block;font-size:16px;font-weight:600;line-height:1.3;color:var(--ink-strong)}
        .vl-live-search-option-addr{display:block;margin-top:2px;font-size:13px;line-height:1.4;color:var(--ink-muted)}
        .vl-live-search-status{margin:8px 2px 0;font-size:12px;line-height:1.4;color:var(--ink-muted)}
        .vl-live-search-status-error{color:#6e4a18}
        .vl-live-search-status button{padding:0;border:0;background:transparent;color:var(--green);font:inherit;font-weight:700;text-decoration:underline;cursor:pointer}

        /* NOW figures - tightened to the home scale. The place name is a clean
           20px/700, the address a muted 15px (was an oversized 20px that made the
           header feel loose), figures stay large (the home h1 rung) and body/cond
           text drops to the home 17px with the home muted tone. */
        .vl-live-place{margin:0 0 4px;font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;color:#000}
        .vl-live-place-addr{margin:0 0 28px;max-width:62ch;font-size:15px;font-weight:400;line-height:1.5;letter-spacing:0;color:rgba(0,0,0,.54)}

        .vl-live-data-error{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 24px;padding:14px 16px;border:1px solid #e8c547;border-radius:14px;background:var(--tint-warn);font-size:13px;color:#6e4a18}
        .vl-live-data-error button{min-height:34px;padding:0 12px;border:1px solid #6e4a18;border-radius:999px;background:#fff;color:#6e4a18;font:inherit;font-weight:700;cursor:pointer}
        .vl-live-data-skeleton{display:grid;gap:9px;margin:0 0 24px;padding:18px;border:1px solid var(--hair);border-radius:14px}
        .vl-live-data-skeleton i{height:12px;border-radius:999px;background:linear-gradient(90deg,#eef1ee,#f7f8f7,#eef1ee);background-size:200% 100%;animation:vl-live-shimmer 1.2s linear infinite}
        .vl-live-data-skeleton i:nth-child(2){width:72%}.vl-live-data-skeleton i:nth-child(3){width:86%}.vl-live-data-skeleton i:nth-child(4){width:58%}
        .vl-live-sub-fact.is-stale{color:#8a5a1f}
        @keyframes vl-live-shimmer{to{background-position:-200% 0}}
        .vl-live-now{padding-top:0;border-top:0}
        .vl-live-empty-selection{padding-top:8px}
        .vl-live-now-compact{padding-top:0}
        .vl-live-now-split{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));border-top:1px solid var(--hair);border-bottom:1px solid var(--hair)}
        .vl-live-now-pane{padding:18px 16px 18px 0;min-width:0}
        .vl-live-now-pane+.vl-live-now-pane{padding-left:16px;border-left:1px solid var(--hair)}
        .vl-live-now-main{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
        .vl-live-now-main strong{font-size:clamp(28px,3vw,38px);line-height:1;font-weight:650;letter-spacing:-.04em;color:#1a1a1a}
        .vl-live-now-main span{font-size:14px;font-weight:600;color:var(--green)}
        .vl-live-now-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-bottom:1px solid var(--hair)}
        .vl-live-now-facts>div{padding:14px 12px 14px 0;min-width:0}
        .vl-live-now-facts>div+div{padding-left:12px;border-left:1px solid var(--hair)}
        .vl-live-now-facts span{display:block;font-size:10px;font-weight:650;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-muted)}
        .vl-live-now-facts strong{display:block;margin-top:5px;font-size:13px;color:#1a1a1a}
        .vl-live-health-compact,.vl-live-best-compact{margin-top:16px;padding:14px 16px;border-radius:12px;background:rgba(209,244,112,.16)}
        .vl-live-health-compact p:last-child{margin:0;font-size:13px;line-height:1.5;color:rgba(0,0,0,.72)}
        .vl-live-best-compact strong{display:block;font-size:20px;color:#1a1a1a}
        .vl-live-best-compact span{display:block;margin-top:5px;font-size:12px;color:var(--ink-muted)}
        .vl-live-detail-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:18px}
        .vl-live-detail-head .vl-live-h2{margin:0}
        .vl-live-detail-tabs{display:inline-flex;padding:3px;border-radius:999px;background:var(--ground);border:1px solid var(--hair)}
        .vl-live-detail-tabs button{min-height:34px;padding:0 14px;border:0;border-radius:999px;background:transparent;color:var(--green);font:inherit;font-size:12px;font-weight:700;cursor:pointer}
        .vl-live-detail-tabs button[aria-selected="true"]{background:var(--lime);color:var(--green)}
        .vl-live-detail-tabs button:focus-visible{outline:3px solid var(--green);outline-offset:2px}
        .vl-live-detail-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));border-top:1px solid var(--hair)}
        .vl-live-detail-list>div{display:flex;justify-content:space-between;gap:12px;padding:14px 12px 14px 0;border-bottom:1px solid var(--hair)}
        .vl-live-detail-list>div:nth-child(even){padding-left:12px;border-left:1px solid var(--hair)}
        .vl-live-detail-list span{font-size:12px;color:var(--ink-muted)}
        .vl-live-detail-list strong{font-size:13px;color:#1a1a1a;text-align:right}
        @media(max-width:640px){
          .vl-live-now-split{grid-template-columns:1fr}
          .vl-live-now-pane+.vl-live-now-pane{padding-left:0;border-left:0;border-top:1px solid var(--hair)}
          .vl-live-now-facts{grid-template-columns:repeat(2,minmax(0,1fr))}
          .vl-live-now-facts>div+div{border-left:0}
          .vl-live-now-facts>div:nth-child(even){padding-left:12px;border-left:1px solid var(--hair)}
          .vl-live-detail-head{align-items:flex-start;flex-direction:column}
          .vl-live-detail-list{grid-template-columns:1fr}
          .vl-live-detail-list>div:nth-child(even){padding-left:0;border-left:0}
        }
        .vl-live-figure{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:8px 0 0}
        .vl-live-metric-xl{font-size:clamp(40px,4.3vw,56px);font-weight:600;line-height:1.04;letter-spacing:-0.04em;color:#1a1a1a}
        .vl-live-metric-lg{font-size:clamp(32px,3.2vw,40px);font-weight:600;line-height:1.08;letter-spacing:-1.6px;color:#1a1a1a}
        .vl-live-metric-md{display:block;font-size:20px;font-weight:700;line-height:1.25;letter-spacing:-.4px;color:#1a1a1a}
        .vl-live-cond{margin:14px 0 0;max-width:46ch;font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.898)}
        .vl-live-sub-fact{margin:8px 0 0;font-size:14px;line-height:1.5;color:rgba(0,0,0,.54)}

        /* AQI mark - severity encoded by FORM as well as tone. */
        .vl-live-dot{display:inline-block;width:16px;height:16px;border-radius:50%;flex:0 0 auto}
        .vl-live-dot-good{background:var(--aqi-good);border:2px solid var(--green)}
        .vl-live-dot-sat{background:var(--aqi-sat);border:2px solid var(--green)}
        .vl-live-dot-mod{background:var(--aqi-mod);border:2px solid var(--green)}
        .vl-live-dot-poor{background:var(--paper);border:5px solid var(--aqi-poor);box-shadow:0 0 0 1px var(--green)}
        .vl-live-dot-worst{background:var(--aqi-worst);border:3px solid var(--paper);box-shadow:0 0 0 2px var(--aqi-worst),0 0 0 3px var(--green)}

        .vl-live-cat{display:inline-flex;align-items:center;padding:5px 14px;border:1.5px solid #1a3a2a;border-radius:var(--r-pill);background:var(--paper);font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#1a3a2a;white-space:nowrap}

        /* Map overlays - inset from the bottom corners (Maps Platform ToS). No rule
           anywhere targets .gm-style-cc, a[href*="google"] or img[alt="Google"]. */
        .vl-live-map-controls{position:absolute;top:84px;right:18px;left:auto;z-index:6;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
        /* FINAL AGREED DESIGN - the resting AQI/PM2.5 selector pills are transparent with a
           subtle dark-green outline and dark-green text (no frosted white fill, no backdrop
           blur, no resting shadow). Hover gives a light lime tint only (no heavy shadow). */
        .vl-live-layer{min-height:44px;padding:0 18px;border:1.5px solid #1a3a2a;border-radius:var(--r-pill);background:transparent;color:#1a3a2a;font:inherit;font-size:14px;font-weight:600;letter-spacing:-.125px;cursor:pointer;transition:background-color .2s,border-color .2s,transform .2s}
        .vl-live-layer:hover{border-color:#1a3a2a;background:var(--lime-tint);transform:translateY(-2px)}
        .vl-live-layer:focus-visible{outline:3px solid var(--green);outline-offset:3px}
        /* FINAL AGREED DESIGN - the active AQI/PM2.5 selector tab presents a TRANSLUCENT lime
           (#d1f470-based) fill with #1a3a2a text/boundary, distinct from the fully-opaque lime.
           The lime lives on the SELECTOR chrome, not on the data tiles. */
        .vl-live-layer[aria-pressed="true"]{border-color:#1a3a2a;background:rgba(209,244,112,.55);color:#1a3a2a;font-weight:700}

        /* FEAT-004 - Google-Destinations-style BOTTOM SELECTED-PLACE BAR. A floating,
           centered, pill-ish card over the roadmap showing the selected destination
           name + location/type + a chevron. INSET from the bottom corners (bottom:36px,
           max-width + horizontal margin) so Google's bottom-left logo and bottom-right
           .gm-style-cc legal attribution stay fully visible per the Maps Platform ToS -
           no rule anywhere targets .gm-style-cc / a[href*="google"] / img[alt="Google"].
           White surface, dark-green #1a3a2a text, 14px home panel radius, only a light
           elevation (it floats over the map), lime #d1f470 reserved for the chevron
           accent. z-index sits below the search dropdown (z-7) but above the canvas. */
        .vl-live-map-destbar{position:absolute;left:50%;bottom:36px;transform:translateX(-50%);z-index:6;display:flex;align-items:center;gap:12px;max-width:min(420px,calc(100% - 96px));min-height:48px;padding:10px 16px;border:1px solid var(--hair);border-radius:14px;background:var(--paper);color:#1a3a2a;font:inherit;text-align:left;cursor:pointer;box-shadow:none;transition:box-shadow .2s,transform .2s}
        .vl-live-map-destbar:hover{transform:translateX(-50%) translateY(-1px);box-shadow:0 4px 14px rgba(26,58,42,.16)}
        .vl-live-map-destbar:focus-visible{outline:3px solid var(--green);outline-offset:3px}
        .vl-live-map-destbar-text{flex:1 1 auto;min-width:0;display:flex;align-items:baseline;gap:8px;overflow:hidden;white-space:nowrap}
        .vl-live-map-destbar-name{font-size:14px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#1a3a2a;flex:0 0 auto;max-width:60%;overflow:hidden;text-overflow:ellipsis}
        .vl-live-map-destbar-sep{color:rgba(26,58,42,.5);flex:0 0 auto}
        .vl-live-map-destbar-meta{font-size:13px;font-weight:500;color:rgba(26,58,42,.66);overflow:hidden;text-overflow:ellipsis;min-width:0}
        .vl-live-map-destbar-chevron{flex:0 0 auto;font-size:20px;line-height:1;font-weight:700;color:#1a3a2a}

        /* Heatmap scale legend - now rendered INSIDE the left card's layer-result block
           (no longer an absolute on-map overlay). It reuses the no-red --aqi-* ramp
           (dark green -> lime -> amber) and labels both ends in WORDS so colour is never
           the sole carrier of meaning. */
        .vl-live-scale-legend{margin-top:16px;padding:10px 12px;border:1px solid rgba(209,244,112,.9);border-radius:12px;background:#fff}
        .vl-live-scale{height:8px;border-radius:var(--r-pill);background:linear-gradient(90deg,var(--aqi-good) 0%,var(--aqi-sat) 22%,var(--aqi-mod) 48%,var(--aqi-poor) 74%,var(--aqi-worst) 100%)}
        .vl-live-scale-ends{display:flex;justify-content:space-between;margin-top:6px;gap:8px}
        .vl-live-scale-ends span{font-size:11px;font-weight:700;color:var(--green)}

        /* SELECTED-PLACE CARD (left column). FINAL TARGET: the photo + lime number pill
           relocated OFF the map into this card, which leads the left column. The card uses
           the home panel radius (14px) and hairline, no resting shadow. */
        .vl-live-place-card{position:relative;border:1px solid var(--hair);border-radius:14px;background:#fff;outline:none}
        .vl-live-place-card::after{content:'';position:absolute;left:50%;bottom:-7px;width:14px;height:14px;border-right:1px solid var(--hair);border-bottom:1px solid var(--hair);background:#fff;transform:translateX(-50%) rotate(45deg);z-index:0}
        .vl-live-place-card:focus-visible{outline:3px solid var(--green);outline-offset:4px}
        .vl-live-photo-shell{overflow:hidden;border-radius:13px 13px 0 0}
        .vl-live-place-body{position:relative;z-index:1;background:#fff;border-radius:0 0 13px 13px}
        .vl-live-place-body{padding:20px}
        .vl-live-place-body .vl-live-place{margin-top:0}
        /* Real place metadata / attributes / description / supporting info. Each block
           renders only when the datum exists; honest degradation keeps them empty when no
           key => no fetch. Tokens match the home ladder: hairline rules, muted ink, no
           red, lime check marks reuse --green. The address loses its default 28px gap when
           metadata follows so the card reads as one continuous block. */
        .vl-live-place-facts{margin:0;display:grid;gap:10px}
        .vl-live-place-fact{display:flex;justify-content:space-between;gap:14px;align-items:baseline;padding-bottom:10px;border-bottom:1px solid var(--hair)}
        .vl-live-place-fact dt{margin:0;font-size:12px;font-weight:600;letter-spacing:.01em;color:rgba(0,0,0,.54)}
        .vl-live-place-fact dd{margin:0;font-size:14px;font-weight:600;line-height:1.35;color:#1a1a1a;text-align:right}
        .vl-live-place-attrs{margin:16px 0 0;padding:0;list-style:none;display:grid;gap:8px}
        .vl-live-place-attrs li{display:flex;align-items:center;gap:8px;font-size:14px;line-height:1.4;color:#1a1a1a}
        .vl-live-place-attrs svg{display:block;flex:0 0 auto}
        .vl-live-place-desc{margin:16px 0 0;max-width:62ch;font-size:15px;line-height:1.5;color:rgba(0,0,0,.72)}
        .vl-live-place-support{margin:16px 0 0;padding:0 0 0 18px;list-style:none;display:grid;gap:6px}
        .vl-live-place-support li{position:relative;font-size:13px;line-height:1.45;color:rgba(0,0,0,.54)}
        .vl-live-place-support li::before{content:'•';position:absolute;left:-14px;color:var(--green)}
        /* PM2.5 result "Current status / <word>" (FINAL TARGET mockup). No red. */
        .vl-live-status-label{margin-top:14px}
        .vl-live-status-word{margin:2px 0 0;font-size:17px;font-weight:700;line-height:1.25;color:#1a1a1a}
        .vl-live-layer-result{margin-top:20px;padding-top:20px;border-top:1px solid var(--hair)}
        .vl-live-layer-result .vl-live-figure{margin-top:4px}
        .vl-live-layer-advisory{margin-top:14px;font-size:17px}
        .vl-live-photo-shell{position:relative;margin:0}
        .vl-live-place-photos{display:flex;gap:0;overflow-x:auto;overflow-y:hidden;scroll-snap-type:x mandatory;scrollbar-width:none}
        .vl-live-place-photos::-webkit-scrollbar{display:none}
        /* The photo cells sit on the SAME exact lime (--lime #d1f470) as the number pill
           (req 01: photo + pill share the same lime), so a loading/absent image reads as
           the pill's lime rather than the lighter --lime-solid used before. */
        .vl-live-photo-page{display:block;flex:0 0 100%;height:260px;padding:0;scroll-snap-align:start;background:var(--lime)}
        .vl-live-place-photo{position:relative;width:100%;height:100%;margin:0;overflow:hidden;background:var(--lime)}
        .vl-live-place-photo.is-primary{width:100%;height:100%}
        .vl-live-place-photo.is-secondary{border-radius:0}
        .vl-live-place-photo img{display:block;width:100%;height:100%;object-fit:cover}
        .vl-live-photo-credit{position:absolute;right:6px;bottom:5px;left:6px;z-index:2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:3px 6px;border-radius:7px;background:rgba(255,255,255,.76);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);font-size:8px;line-height:1.2;color:rgba(26,58,42,.78)}
        .vl-live-photo-credit a{color:inherit;text-decoration:none}
        .vl-live-photo-credit a:hover{text-decoration:underline}
        /* Number-only pill (req 01): the numeric count + a decorative referee SVG on
           the lime pill background. No word text, no red. */
        .vl-live-photo-count{position:absolute;top:12px;left:12px;z-index:4;display:inline-flex;align-items:center;gap:4px;padding:5px 10px 5px 6px;border-radius:999px;background:var(--lime);color:var(--green);font-size:13px;font-weight:800;line-height:1;box-shadow:none}
        .vl-live-photo-count svg{display:block;width:20px;height:20px;flex:0 0 auto}
        .vl-live-photo-tabs{display:flex;gap:5px;margin:0;padding:7px 11px 11px;height:auto;align-items:center}
        .vl-live-photo-tab{position:relative;display:block;flex:1 1 0;height:14px;min-width:10px;cursor:pointer;outline:none}
        .vl-live-photo-tab::after{content:'';position:absolute;left:0;right:0;top:50%;height:2px;border-radius:999px;background:#e7ebe8;transform:translateY(-50%);transition:background-color .18s ease,transform .18s ease}
        .vl-live-photo-tab[aria-selected="true"]::after{background:var(--green);transform:translateY(-50%) scaleY(1.5)}
        .vl-live-photo-tab:focus-visible::before{content:'';position:absolute;inset:1px;border:1px solid var(--green);border-radius:999px}

        /* Continuous weather workspace: typography + hairlines instead of repeated cards. */
        .vl-live-signal-stack{padding-top:0;padding-bottom:0}
        .vl-live-signal{padding:34px 0;border-top:1px solid var(--hair)}
        .vl-live-signal:last-child{border-bottom:1px solid var(--hair)}
        .vl-live-signal-head{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;align-items:end}
        .vl-live-signal-head .vl-live-eyebrow{margin-bottom:10px}
        .vl-live-signal-head .vl-live-h2{margin-bottom:0}
        .vl-live-signal-summary{margin:0;max-width:34ch;font-size:14px;line-height:1.45;color:var(--ink-muted)}
        .vl-live-signal-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin-top:24px;border-top:1px solid var(--hair)}
        .vl-live-signal-facts>div{padding:16px 14px 0 0}
        .vl-live-signal-facts>div:nth-child(even){padding-left:14px;border-left:1px solid var(--hair)}
        .vl-live-signal-facts strong{font-size:17px;line-height:1.25;color:#1a1a1a}
        @container vllive (min-width:620px){
          .vl-live-signal-head{grid-template-columns:minmax(0,1fr) minmax(180px,.45fr);gap:24px}
          .vl-live-signal-summary{text-align:right;justify-self:end}
          .vl-live-signal-facts{grid-template-columns:repeat(4,minmax(0,1fr))}
          .vl-live-signal-facts>div{padding:16px 16px 0}
          .vl-live-signal-facts>div:first-child{padding-left:0}
          .vl-live-signal-facts>div+div{border-left:1px solid var(--hair)}
        }

        /* Screenshot-led hourly workspace: one horizontal table, shared columns, no card pile. */
        .vl-live-forecast-board{overflow:hidden;border:1px solid rgba(209,244,112,.72);border-radius:18px;background:#fff}
        .vl-live-forecast-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;padding:20px;background:linear-gradient(135deg,rgba(209,244,112,.24),rgba(255,255,255,.98))}
        .vl-live-forecast-head .vl-live-h2{margin:3px 0 0}
        .vl-live-forecast-head>time{font-size:12px;font-weight:700;color:var(--green);white-space:nowrap}
        .vl-live-hour-rail-primary{border-radius:0;border-top:1px solid var(--hair);border-bottom:1px solid var(--hair)}
        .vl-live-forecast-row{padding-top:16px}
        .vl-live-forecast-row+.vl-live-forecast-row{border-top:1px solid var(--hair)}
        .vl-live-forecast-label{display:flex;justify-content:space-between;gap:12px;margin:0;padding:0 20px 10px;font-size:12px;font-weight:700;color:var(--ink-muted)}
        .vl-live-forecast-label span{font-weight:600}
        .vl-live-metric-rail{display:flex;overflow-x:auto;scroll-snap-type:x proximity;scrollbar-color:var(--lime) transparent;scrollbar-width:thin}
        .vl-live-metric-cell{position:relative;flex:0 0 112px;min-height:86px;padding:12px 12px 18px;border-right:1px solid var(--hair);scroll-snap-align:start;background:#fff}
        .vl-live-metric-cell:first-child{background:rgba(209,244,112,.16)}
        .vl-live-metric-cell strong{display:block;font-size:17px;line-height:1.1;color:#1a1a1a}
        .vl-live-metric-cell span{display:block;margin-top:5px;font-size:10px;color:var(--ink-muted)}
        .vl-live-temp-line,.vl-live-rain-line,.vl-live-uv-line,.vl-live-aq-line{position:absolute;left:12px;right:12px;bottom:9px;height:2px;border-radius:999px;background:var(--lime)}
        .vl-live-temp-line::after,.vl-live-aq-line::after{content:'';position:absolute;right:0;top:50%;width:6px;height:6px;border-radius:50%;background:var(--green);transform:translateY(-50%)}
        .vl-live-rain-line{background:linear-gradient(90deg,var(--green),var(--lime))}
        .vl-live-uv-line{background:linear-gradient(90deg,#7ab75a,var(--lime),#d4b33d)}
        .vl-live-aq-line{background:linear-gradient(90deg,var(--green),var(--aqi-sat),var(--lime))}

        /* Compact near-term planning panel from the supplied trip reference, restyled to Home. */
        .vl-live-plan-card{margin-top:28px;padding:22px;border:1px solid var(--hair);border-radius:18px;background:#fff}
        .vl-live-plan-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}
        .vl-live-plan-title{margin:0;font-size:22px;line-height:1.2;font-weight:700;letter-spacing:-.4px;color:#1a1a1a}
        .vl-live-plan-place{margin:6px 0 0;font-size:13px;line-height:1.45;color:var(--ink-muted)}
        .vl-live-plan-range{margin:0;font-size:12px;line-height:1.4;color:var(--ink-muted);text-align:right}
        .vl-live-plan-days{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:20px}
        .vl-live-plan-day{min-width:0;padding:16px 12px;border-radius:14px;background:#fafafa;text-align:center}
        .vl-live-plan-day strong,.vl-live-plan-day b,.vl-live-plan-day p{display:block}
        .vl-live-plan-day strong{font-size:13px;color:var(--ink-muted)}
        .vl-live-plan-day img{display:block;width:38px;height:38px;margin:10px auto}
        .vl-live-plan-day b{font-size:18px;color:#1a1a1a}
        .vl-live-plan-day b span{font-size:13px;font-weight:600;color:var(--ink-muted)}
        .vl-live-plan-day p{margin:8px 0 0;font-size:11px;line-height:1.35;color:var(--ink-muted)}
        .vl-live-plan-context{display:grid;gap:18px;margin-top:22px;padding-top:20px;border-top:1px solid var(--hair)}
        .vl-live-plan-context>div+div{padding-top:18px;border-top:1px solid var(--hair)}
        .vl-live-plan-context strong{font-size:14px;color:#1a1a1a}
        .vl-live-plan-pollen{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));overflow:hidden;border:1px solid var(--hair);border-radius:999px}
        .vl-live-plan-pollen span{padding:10px 12px;text-align:center;font-size:13px;font-weight:600;color:var(--ink-second)}
        .vl-live-plan-pollen span+span{border-left:1px solid var(--hair)}

        .vl-live-best-outside{display:grid;gap:10px;padding:24px;border:2px solid var(--lime);border-radius:14px;background:var(--lime-tint);color:var(--ink-base)}
        .vl-live-best-outside .vl-live-metric-lg,.vl-live-best-outside .vl-live-body{color:var(--ink-head)}
        .vl-live-best-outside .vl-live-small{color:var(--ink-muted)}
        .vl-live-hour-rail,.vl-live-day-rail{display:flex;gap:0;overflow-x:auto;scroll-snap-type:x proximity;padding:0;border-top:1px solid var(--hair);border-bottom:1px solid var(--hair);scrollbar-width:thin}

        .vl-live-hour-rail,.vl-live-day-rail,.vl-live-metric-rail{
          scrollbar-color:#d1f470 #fafafa;
          scrollbar-width:thin;
        }
        .vl-live-hour-rail::-webkit-scrollbar,
        .vl-live-day-rail::-webkit-scrollbar,
        .vl-live-metric-rail::-webkit-scrollbar{height:8px}
        .vl-live-hour-rail::-webkit-scrollbar-track,
        .vl-live-day-rail::-webkit-scrollbar-track,
        .vl-live-metric-rail::-webkit-scrollbar-track{background:#fafafa;border-radius:999px}
        .vl-live-hour-rail::-webkit-scrollbar-thumb,
        .vl-live-day-rail::-webkit-scrollbar-thumb,
        .vl-live-metric-rail::-webkit-scrollbar-thumb{background:#d1f470;border:2px solid #fafafa;border-radius:999px}
        .vl-live-hour-rail::-webkit-scrollbar-thumb:hover,
        .vl-live-day-rail::-webkit-scrollbar-thumb:hover,
        .vl-live-metric-rail::-webkit-scrollbar-thumb:hover{background:#1a3a2a}
        .vl-live-hour-card{position:relative;flex:0 0 112px;min-height:144px;padding:14px 14px 14px 0;border:0;border-radius:0;background:transparent;scroll-snap-align:start}
        .vl-live-hour-card+.vl-live-hour-card{padding-left:14px;border-left:1px solid var(--hair)}
        .vl-live-hour-card time,.vl-live-hour-card span{display:block;font-size:12px;line-height:1.35;color:var(--ink-muted)}
        .vl-live-hour-card strong{display:block;margin:9px 0;font-size:19px;color:var(--green)}
        .vl-live-hour-card img{display:block;width:30px;height:30px;margin-top:8px}
        .vl-live-hour-card em{position:absolute;top:8px;right:8px;font-size:9px;font-style:normal;font-weight:700;color:var(--green)}
        .vl-live-hour-card-air{flex-basis:128px}
        .vl-live-insight-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-top:1px solid var(--hair);border-bottom:1px solid var(--hair)}
        .vl-live-insight-grid>div{padding:18px 16px}
        .vl-live-insight-grid>div+div{border-left:1px solid var(--hair)}
        .vl-live-insight-grid strong{font-size:15px;color:var(--green)}
        .vl-live-minor-title{margin:28px 0 12px;font-size:16px;font-weight:700;color:#1a1a1a}
        .vl-live-history-head{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-top:24px}
        .vl-live-history-head .vl-live-minor-title{margin:0}
        .vl-live-history-controls{display:flex;gap:6px}
        .vl-live-history-controls button{min-height:34px;padding:0 11px;border:1px solid var(--hair);border-radius:999px;background:#fff;color:var(--green);font:inherit;font-size:12px;font-weight:700;cursor:pointer}
        .vl-live-history-controls button[aria-pressed="true"]{border-color:var(--green);background:var(--lime)}
        .vl-live-history{height:132px;display:flex;align-items:flex-end;gap:2px;margin-top:14px;padding:10px 0 2px;border-bottom:1px solid var(--hair)}
        .vl-live-history i{flex:1 1 0;min-width:2px;max-width:10px;border-radius:4px 4px 0 0;background:linear-gradient(180deg,var(--lime),var(--green))}
        .vl-live-weather-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));border-top:1px solid var(--hair)}
        .vl-live-weather-grid>div{padding:16px 14px 16px 0;border-bottom:1px solid var(--hair)}
        .vl-live-weather-grid>div:nth-child(even){padding-left:14px;border-left:1px solid var(--hair)}
        .vl-live-weather-grid strong{font-size:15px;color:#1a1a1a}
        .vl-live-sunline{display:grid;grid-template-columns:1fr 1fr;margin-top:18px;border-top:1px solid var(--hair);border-bottom:1px solid var(--hair);border-radius:0;overflow:hidden}
        .vl-live-sunline>div{padding:16px}
        .vl-live-sunline>div+div{border-left:1px solid var(--hair)}
        .vl-live-day-card{flex:0 0 112px;min-height:150px;padding:14px 14px 14px 0;border:0;border-radius:0;background:transparent;scroll-snap-align:start;text-align:left}
        .vl-live-day-card+.vl-live-day-card{padding-left:14px;border-left:1px solid var(--hair)}
        .vl-live-day-card>span,.vl-live-day-card>b{display:block;margin-top:5px;font-size:12px;color:var(--ink-muted)}
        .vl-live-day-card>b{font-size:14px;color:#1a1a1a}
        .vl-live-day-card img{width:34px;height:34px;margin:8px auto 2px}
        .vl-live-alerts{margin-top:24px}
        .vl-live-alert{padding:16px;border-radius:14px;background:var(--tint-warn)}
        .vl-live-alert+.vl-live-alert{margin-top:8px}
        .vl-live-alert strong{display:block;color:#6e4a18}
        .vl-live-alert p{margin:6px 0 0;font-size:13px;line-height:1.45;color:#5f4a2b}
        .vl-live-alert span{display:block;margin-top:6px;font-size:11px;color:#7f6845}
        .vl-live-pollen-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0;border-top:1px solid var(--hair);border-bottom:1px solid var(--hair)}
        .vl-live-pollen-card{padding:16px 14px 16px 0;border:0;border-radius:0;background:transparent}
        .vl-live-pollen-card:nth-child(even){padding-left:14px;border-left:1px solid var(--hair)}
        .vl-live-pollen-card:nth-child(n+3){border-top:1px solid var(--hair)}
        .vl-live-pollen-card strong{display:block;font-size:15px;color:#1a1a1a}
        .vl-live-pollen-card span{display:block;margin-top:5px;font-size:12px;color:var(--ink-muted)}

        /* The old two-/four-up "Conditions" fact rail (.vl-live-rail/.vl-live-fact) was
           replaced by the continuous .vl-live-signal-stack bands; its rules are deleted
           here per this file's "unused rules are deleted" convention. */

        /* Health advisory accent rule. */
        .vl-live-advisory-rule{display:block;height:3px;width:120px;margin:30px 0 0;background:var(--lime)}

        /* Pollutant rows. */
        .vl-live-prow{display:grid;grid-template-columns:92px minmax(0,1fr);gap:8px 16px;align-items:center;padding:16px 0;border-bottom:1px solid var(--hair)}
        .vl-live-prow:first-of-type{border-top:1px solid var(--hair)}
        .vl-live-prow .vl-live-label{margin:0}
        .vl-live-prow .vl-live-track{grid-column:2}
        .vl-live-prow .vl-live-metric-md,.vl-live-prow .vl-live-prow-cat{grid-column:2;text-align:left}
        .vl-live-prow .vl-live-metric-md{font-size:17px}
        @container vllive (min-width:560px){
          .vl-live-prow{grid-template-columns:100px minmax(0,1fr) 104px 112px;gap:16px}
          .vl-live-prow .vl-live-metric-md{grid-column:3;text-align:right}
          .vl-live-prow .vl-live-prow-cat{grid-column:4;text-align:right}
        }
        .vl-live-track{display:block;height:8px;background:var(--ground);border-radius:2px;overflow:hidden}
        .vl-live-bar{display:block;height:100%}
        .vl-live-bar-good{background:var(--aqi-good)}
        .vl-live-bar-sat{background:var(--aqi-sat)}
        .vl-live-bar-mod{background:var(--aqi-mod)}
        .vl-live-bar-poor{background:var(--aqi-poor)}
        .vl-live-bar-worst{background:var(--aqi-worst)}
        .vl-live-prow-cat{font-size:12px;font-weight:700;letter-spacing:.01em;color:var(--ink-muted)}

        .vl-live-section{padding-top:0}

        .vl-live-solar-load{min-height:52px;padding:0 24px;border:2px solid var(--green);border-radius:50px;background:var(--lime);color:var(--green);font:inherit;font-size:17px;font-weight:600;cursor:pointer;transition:background-color .2s,transform .2s,box-shadow .2s}
        .vl-live-solar-load:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .vl-live-solar-load:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

        /* SUBSCRIBE - the shipped .blog-wa-subscribe pill (ROLE 8). */
        .vl-live-wa-subscribe{display:inline-flex;align-items:center;gap:10px;padding:12px 20px;border-radius:999px;background:var(--lime);color:var(--green);font-weight:700;font-size:17px;text-decoration:none;transition:transform .2s,box-shadow .2s}
        .vl-live-wa-subscribe svg{flex:0 0 auto}
        .vl-live-wa-subscribe:hover,.vl-live-wa-subscribe:focus-visible{transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.18)}
        .vl-live-wa-subscribe:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}

        @media(max-width:1023px){
          /* Keep the search centred; the only other on-map control is the AQI|PM2.5
             selector, pinned top-right below the centred field. */
          .vl-live-map-search{top:14px;left:50%;transform:translateX(-50%);width:min(340px,calc(100% - 24px))}
          .vl-live-map-controls{top:78px;right:12px;left:auto}
        }
        @media(max-width:767px){
          .vl-live{padding-bottom:48px}
          .vl-live-wrap{padding-inline:16px}
          .vl-live-insight-grid{grid-template-columns:1fr}
          .vl-live-insight-grid>div+div{border-left:0;border-top:1px solid var(--hair)}
          .vl-live-weather-grid{grid-template-columns:1fr}
          .vl-live-weather-grid>div:nth-child(even){padding-left:0;border-left:0}
          .vl-live-pollen-grid{grid-template-columns:1fr}
          .vl-live-section{padding-top:0}
          .vl-live-block{padding-block:32px}
          .vl-live-left > .vl-live-section{margin-top:64px}
          .vl-live-map-search{top:12px;left:50%;right:auto;transform:translateX(-50%);width:calc(100% - 24px)}
          .vl-live-search{max-width:none}
          .vl-live-map-controls{top:76px;right:12px;left:auto}
          .vl-live-plan-head{display:block}
          .vl-live-plan-range{margin-top:8px;text-align:left}
          .vl-live-plan-days{gap:6px}
          .vl-live-plan-day{padding:14px 8px}
          .vl-live-plan-pollen{grid-template-columns:1fr}
          .vl-live-plan-pollen span+span{border-left:0;border-top:1px solid var(--hair)}
        }
        @media(prefers-reduced-motion:reduce){
          .vl-live-data-skeleton i{animation:none}
          .vl-live-layer,.vl-live-wa-subscribe,.vl-live-solar-load{transition:none}
          .vl-live-layer:hover,.vl-live-wa-subscribe:hover,.vl-live-wa-subscribe:focus-visible,.vl-live-solar-load:hover{transform:none;box-shadow:none}
        }
      `}</style>
    </section>
  );
};

export default VayuLokLive;