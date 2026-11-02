/**
 * Pure helpers, constant tables, and module-level configuration for VayuLokLive.
 *
 * These were extracted VERBATIM from src/components/VayuLokLive.tsx as part of a pure
 * structural refactor (no behaviour change). Every function here is a pure, top-level
 * function with no dependency on component state; the constants are build-time values.
 */

import type {
  AirIndexInfo,
  AirPoint,
  AirState,
  HealthPersonaDefinition,
  HealthPersonaIcon,
  HealthRecommendationKey,
  LocationTimeState,
  PlaceState,
  Sev,
  WeatherHour,
  WorldTimeDestination,
} from './VayuLokLive.types';

export const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_BROWSER_KEY || '';

// Selected-place marker uses Google's canonical Material Symbols Outlined "location_on"
 // glyph (source: google/material-design-icons), presented on the same lime/green circle
 // as the site's icon system. This replaces the oversized bespoke teardrop marker.
export const LOCATION_MARKER_ICON = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent( `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36"><circle cx="18" cy="18" r="17" fill="#d1f470"/><svg x="6" y="6" width="24" height="24" viewBox="0 -960 960 960"><path fill="#1a3a2a" d="M480-480q33 0 56.5-23.5T560-560q0-33-23.5-56.5T480-640q-33 0-56.5 23.5T400-560q0 33 23.5 56.5T480-480Zm0 294q122-112 181-203.5T720-552q0-109-69.5-178.5T480-800q-101 0-170.5 69.5T240-552q0 71 59 162.5T480-186Zm0 106Q319-217 239.5-334.5T160-552q0-150 96.5-239T480-880q127 0 223.5 89T800-552q0 100-79.5 217.5T480-80Zm0-480Z"/></svg></svg>` )}`;

export const DOT_LINE_RGBA: [ number, number, number, number ] = [ 255, 255, 255, 230 ];

// Global map: do not re-introduce a lat/lng restriction here because destination search
// is worldwide. Manual pan/zoom gestures are disabled; only an explicit place selection
// is allowed to move the camera.

// Wait for settled input before requesting Google's paid Places Autocomplete SKU.
// Search still works worldwide and retains its existing session token handling.
export const SEARCH_DEBOUNCE_MS = 300;
export const WORLD_SEARCH_DEBOUNCE_MS = 300;
export const WORLD_SEARCH_MIN_CHARS = 2;
export const FX_API_BASE = 'https://api.frankfurter.dev/v2';
export const ROUTE_REQUEST_ENABLED = process.env.NEXT_PUBLIC_VAYULOK_ROUTE_ENABLED === 'true';
export const FX_RATE_TTL_MS = 6 * 60 * 60 * 1000;

export const FALLBACK_CURRENCY_CODES = [
  'USD', 'INR', 'EUR', 'GBP', 'AED', 'JPY', 'SGD', 'AUD', 'CAD', 'CHF',
  'CNY', 'KRW', 'THB', 'NZD', 'BRL', 'ZAR', 'SAR', 'IDR', 'MYR', 'HKD',
];

export const AQI_HEATMAP_MAP_TYPE = 'UAQI_RED_GREEN';
export const PM25_HEATMAP_MAP_TYPE = 'PM25_INDIGO_PERSIAN';
export const AQI_HEATMAP_TILE_BASE = 'https://airquality.googleapis.com/v1/mapTypes';
export const WEATHER_MAP_TILE_BASE = 'https://weather.googleapis.com/v1/mapTypes';
export const US_PRECIPITATION_MAP_TYPE = 'US_PRECIPITATION_CURRENT';
export const EU_PRECIPITATION_MAP_TYPE = 'EU_PRECIPITATION_CURRENT';

// Weather and Air Quality APIs need a point, not a whole-country coordinate.
// New Delhi is the clearly named first reading; the map initially displays
// India as a region, and explicit place selection zooms to that location.
export const DEFAULT_PLACE: PlaceState = {
  name: 'New Delhi',
  addr: 'Delhi, India',
  lat: 28.6139,
  lng: 77.2090,
  regionCode: 'IN',
};

// A padded overview, not an administrative border: includes the mainland,
// Lakshadweep and the Andaman/Nicobar islands on narrow as well as wide maps.
export const INDIA_OVERVIEW_BOUNDS = {
  north: 37.5,
  south: 6.0,
  east: 98.0,
  west: 67.5,
};

// Selected-place marker uses the current lime/green LOCATION_MARKER_ICON above. Keep this
// comment aligned with the actual marker options so future UI work does not "restore" a retired pin.

// GEOMETRY ON THE REPO PALETTE, ported verbatim from the mock's map styles.
export const MAP_STYLES = [
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

export function aqiCategory( aqi: number ): { word: string; sev: Sev } {
  if ( aqi <= 50 ) return { word: 'Good', sev: 'good' };
  if ( aqi <= 100 ) return { word: 'Satisfactory', sev: 'sat' };
  if ( aqi <= 200 ) return { word: 'Moderate', sev: 'mod' };
  if ( aqi <= 300 ) return { word: 'Poor', sev: 'poor' };
  if ( aqi <= 400 ) return { word: 'Very Poor', sev: 'worst' };
  return { word: 'Severe', sev: 'worst' };
}

export function airQualityCategoryLabel( word: string ): string {
  const clean = String( word || '' ).replace( /\s+/g, ' ' ).trim();
  if ( !clean ) return 'Air quality';
  return /\bair\s+quality$/i.test( clean ) ? clean : `${ clean } air quality`;
}

/* Map Google's returned category TEXT to our no-red severity band. Google drives the word
   (airStateFromApiData prefers idx.category), but the colour/band used to always come from the
   local CPCB threshold - so a reading Google calls e.g. "Good air quality" while the numeric AQI
   sat in the local "Satisfactory" band would show a word and a colour that disagree. Deriving the
   band from the same category text keeps word and colour in step. Returns null when the text is
   not a recognised category, so the caller falls back to the numeric threshold. */
export function severityFromCategory( category?: string ): Sev | null {
  if ( typeof category !== 'string' ) return null;
  const c = category.toLowerCase();
  if ( c.includes( 'excellent' ) || c.includes( 'good' ) ) return 'good';
  if ( c.includes( 'satisfactory' ) || c.includes( 'moderate' ) ) {
    // Google UAQI "Moderate" is a mid band; CPCB "Satisfactory" is better. Treat an explicit
    // "moderate" as the mid band and "satisfactory" as the second band.
    return c.includes( 'moderate' ) ? 'mod' : 'sat';
  }
  if ( c.includes( 'low' ) ) return 'sat';
  if ( c.includes( 'unhealthy for sensitive' ) || c.includes( 'poor' ) ) {
    return c.includes( 'very poor' ) ? 'worst' : 'poor';
  }
  if ( c.includes( 'unhealthy' ) ) return 'poor';
  if ( c.includes( 'very poor' ) || c.includes( 'severe' ) || c.includes( 'hazardous' ) ) return 'worst';
  return null;
}

/* The "Past air quality" history bar's AQI-ramp class. This reuses the SAME band logic as the
   live dot / pollutant tone (aqiCategory) so the history reads with the identical
   good -> sat -> mod -> poor -> worst ramp rather than a flat lime->green gradient. No new
   thresholds are invented here; the single source of truth stays aqiCategory. */
export function aqiBarClass( aqi: number ): string {
  return `vl-live-history-bar-${aqiCategory( aqi ).sev}`;
}

/* Human-readable label for the selected history range, used in the chart's aria-label so a
   screen reader hears "last 24 hours" rather than a raw hour count. */
export function historyRangeLabel( hours: 24 | 168 ): string {
  return hours === 24 ? 'last 24 hours' : 'last 7 days';
}

/* A plain-English "current status" word for the PM2.5 result block, derived from the SAME
   severity band the dot and category already use (never a new scale). The mockup's
   "Elevated" sits in this ramp between the clean and the hazardous ends. */
export function statusWord( sev: Sev ): string {
  switch ( sev ) {
    case 'good': return 'Clean';
    case 'sat': return 'Acceptable';
    case 'mod': return 'Elevated';
    case 'poor': return 'High';
    default: return 'Hazardous';
  }
}

/* Local paths from Google's Material Symbols Outlined set. Keeping the SVG paths local avoids
   a runtime icon-font dependency while preserving Google's icon language across the Air card. */
export const MATERIAL_SYMBOL_PATHS: Record<
  HealthPersonaIcon | 'info' | 'switches' | 'close' | 'air' | 'eco' | 'schedule' | 'location' | 'chevronLeft' | 'chevronRight',
  string
> = {
  info: 'M453-280h60v-240h-60v240Zm50.5-323.2q9.5-9.2 9.5-22.8 0-14.45-9.48-24.22-9.48-9.78-23.5-9.78t-23.52 9.78Q447-640.45 447-626q0 13.6 9.48 22.8 9.48 9.2 23.5 9.2t23.52-9.2ZM480.27-80q-82.74 0-155.5-31.5Q252-143 197.5-197.5t-86-127.34Q80-397.68 80-480.5t31.5-155.66Q143-709 197.5-763t127.34-85.5Q397.68-880 480.5-880t155.66 31.5Q709-817 763-763t85.5 127Q880-563 880-480.27q0 82.74-31.5 155.5Q817-252 763-197.68q-54 54.31-127 86Q563-80 480.27-80Zm.23-60Q622-140 721-239.5t99-241Q820-622 721.19-721T480-820q-141 0-240.5 98.81T140-480q0 141 99.5 240.5t241 99.5Zm-.5-340Z',
  eco: 'M200-120q-33 0-56.5-23.5T120-200q0-11 3-21.5t9-19.5q42-29 90-44.5t98-15.5q20 0 39.5 2.5T498-291q-7-29-24.5-52T430-382q-45-20-67.5-61T340-533q0-83 58.5-141.5T540-733q100 0 170 70t70 170q0 61-25 116.5T684-280q-20 20-46 30t-54 10q-11 0-21.5-1.5T541-247q-9 29-30.5 50.5T460-166q-29 11-60 11H200Zm340-280q50 0 85-35t35-85q0-50-35-85t-85-35q-50 0-85 35t-35 85q0 50 35 85t85 35Z',
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

export const HEALTH_PERSONAS: HealthPersonaDefinition[] = [
  { id: 'general', label: 'General population', apiKey: 'generalPopulation', icon: 'general' },
  { id: 'elderly', label: 'Elderly', apiKey: 'elderly', icon: 'elderly' },
  { id: 'respiratory', label: 'Lung disease', apiKey: 'lungDiseasePopulation', icon: 'respiratory' },
  { id: 'heart', label: 'Heart disease', apiKey: 'heartDiseasePopulation', icon: 'heart' },
  { id: 'athletes', label: 'Athletes', apiKey: 'athletes', icon: 'athletes' },
  { id: 'pregnant', label: 'Pregnant women', apiKey: 'pregnantWomen', icon: 'pregnant' },
  { id: 'children', label: 'Children', apiKey: 'children', icon: 'children' },
];

export function cleanAirInfo( value?: string ): string | undefined {
  if ( typeof value !== 'string' ) return undefined;
  const clean = value.replace( /\s+/g, ' ' ).trim();
  return clean || undefined;
}

export function shortAirInfo( value?: string, max = 72 ): string | undefined {
  const clean = cleanAirInfo( value );
  if ( !clean ) return undefined;
  const firstSentence = clean.match( /^.*?[.!?](?:\s|$)/ )?.[ 0 ]?.trim();
  const candidate = firstSentence && firstSentence.length <= max ? firstSentence : clean;
  if ( candidate.length <= max ) return candidate;
  const clipped = candidate.slice( 0, Math.max( 1, max - 1 ) ).replace( /\s+\S*$/, '' ).trim();
  return `${clipped || candidate.slice( 0, Math.max( 1, max - 1 ) ).trim()}…`;
}

export function directDistanceKm( from: PlaceState, to: PlaceState ): number {
  const toRad = ( value: number ) => value * Math.PI / 180;
  const radiusKm = 6371.0088;
  const lat1 = toRad( from.lat );
  const lat2 = toRad( to.lat );
  const dLat = lat2 - lat1;
  const dLng = toRad( to.lng - from.lng );
  const a = Math.sin( dLat / 2 ) ** 2
    + Math.cos( lat1 ) * Math.cos( lat2 ) * Math.sin( dLng / 2 ) ** 2;
  return radiusKm * 2 * Math.atan2( Math.sqrt( a ), Math.sqrt( 1 - a ) );
}

export function routeDurationLabel( seconds: number ): string {
  const totalMinutes = Math.max( 1, Math.round( seconds / 60 ) );
  const hours = Math.floor( totalMinutes / 60 );
  const minutes = totalMinutes % 60;
  if ( !hours ) return `${minutes} min`;
  if ( !minutes ) return `${hours} hr`;
  return `${hours} hr ${minutes} min`;
}

export function routeDistanceLabel( meters: number ): string {
  if ( meters < 1000 ) return `${Math.max( 1, Math.round( meters ) )} m`;
  const km = meters / 1000;
  return `${km >= 100 ? Math.round( km ) : km.toFixed( 1 )} km`;
}

export const DEFAULT_LOCATION_TIME: LocationTimeState = {
  timeZoneId: 'Asia/Kolkata',
  timeZoneName: 'India Standard Time',
  shortLabel: 'IST',
  source: 'default',
};
export const PENDING_LOCATION_TIME: LocationTimeState = {
  timeZoneId: 'UTC', timeZoneName: '', shortLabel: 'UTC', source: 'pending',
};
export const UNAVAILABLE_LOCATION_TIME: LocationTimeState = {
  timeZoneId: 'UTC', timeZoneName: '', shortLabel: 'UTC', source: 'unavailable',
};

export const DEFAULT_WORLD_TIME_DESTINATION: WorldTimeDestination = {
  name: 'London',
  addr: 'London, United Kingdom',
  lat: 51.5072,
  lng: -0.1276,
  regionCode: 'GB',
  time: {
    timeZoneId: 'Europe/London',
    timeZoneName: 'United Kingdom Time',
    shortLabel: 'Local',
    source: 'fixed',
  },
};

// Google Weather publicAlerts coverage (Google Weather coverage page, checked 2026-10-12).
// Do not bill unsupported regions (including India); supported regions query live alerts.
export const WEATHER_ALERT_REGION_CODES = new Set( [
  'AT','AU','BA','BE','BG','BR','CH','CI','CO','CY','CZ','DE','DK','EC','EE','ES','FI','FR',
  'GB','GH','GR','HR','HU','IE','IS','IT','JM','JP','KR','LT','LU','LV','MG','MK','MX','NL',
  'NO','NZ','PH','PL','PT','RO','RS','SB','SE','SG','SI','SK','TH','TW','US','VN',
] );

export const COMPASS = [ 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW' ];
export function windDirection( deg: number ): string {
  return COMPASS[ Math.round( deg / 45 ) % 8 ];
}
export function clamp( value: number, min: number, max: number ): number {
  return Math.min( max, Math.max( min, value ) );
}
// The Air Quality API returns concentration units as long SCREAMING_SNAKE enums
// (MICROGRAMS_PER_CUBIC_METER, PARTS_PER_BILLION, ...). Rendered verbatim they blow
// out the value column and collide with the category word. Map them to short symbols.
export function concUnitLabel( unit?: string ): string {
  switch ( unit ) {
    case 'MICROGRAMS_PER_CUBIC_METER': return '\u00B5g/m\u00B3';
    case 'PARTS_PER_BILLION': return 'ppb';
    case 'PARTS_PER_MILLION': return 'ppm';
    case 'MILLIGRAMS_PER_CUBIC_METER': return 'mg/m\u00B3';
    case 'NANOGRAMS_PER_CUBIC_METER': return 'ng/m\u00B3';
    default: return unit || '';
  }
}

// Plain-language expansion of the short unit symbol, surfaced as a title/tooltip so a reader who
// does not know "ppb" or "µg/m³" can still understand the number. Keyed on the short symbol that
// concUnitLabel produces.
export function unitTermLabel( unitSymbol: string ): string {
  switch ( unitSymbol ) {
    case '\u00B5g/m\u00B3': return 'micrograms per cubic metre';
    case 'mg/m\u00B3': return 'milligrams per cubic metre';
    case 'ng/m\u00B3': return 'nanograms per cubic metre';
    case 'ppb': return 'parts per billion';
    case 'ppm': return 'parts per million';
    default: return unitSymbol;
  }
}

// Honest display of a pollutant concentration. Google returns a precise number; blindly rounding
// to an integer turns a real trace reading (e.g. 0.4 µg/m³) into "0", which reads as "no
// pollutant" and misrepresents the measurement. Instead, show precision according to magnitude so
// the Google-returned value is preserved faithfully:
//   - a genuine 0 stays "0"
//   - values >= 1 render as a rounded integer (e.g. 32)
//   - values below 1 keep up to two significant decimals (0.4 -> "0.4", 0.04 -> "0.04")
// No "<1" placeholder and no fabricated digits - the string reflects the actual API value.
export function formatPollutantValue( value: number ): string {
  if ( !Number.isFinite( value ) ) return '';
  if ( value === 0 ) return '0';
  const abs = Math.abs( value );
  if ( abs >= 1 ) return String( Math.round( value ) );
  // Sub-1: show enough decimals to carry the first two significant figures, then trim trailing
  // zeros so 0.40 -> "0.4" and 0.04 -> "0.04" without inventing precision the value lacks.
  const decimals = Math.min( 4, 1 - Math.floor( Math.log10( abs ) ) );
  return parseFloat( value.toFixed( decimals ) ).toString();
}

// Short display label for the wind-speed unit the Weather API returns on wind.speed.unit
// (e.g. KILOMETERS_PER_HOUR, MILES_PER_HOUR). Fall back to km/h under unitsSystem=METRIC.
export function windUnitLabel( unit?: string ): string {
  switch ( unit ) {
    case 'MILES_PER_HOUR': return 'mph';
    case 'METERS_PER_SECOND': return 'm/s';
    case 'KILOMETERS_PER_HOUR': return 'km/h';
    default: return 'km/h';
  }
}

export function n( value: unknown ): number {
  const out = Number( value );
  return Number.isFinite( out ) ? out : NaN;
}

export function weatherHourFromApi( row: Record<string, any> ): WeatherHour | null {
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
  if ( Number.isFinite( windDeg ) ) {
    out.windDir = windDirection( windDeg );
    out.windDeg = ( ( windDeg % 360 ) + 360 ) % 360;
  }
  if ( typeof row?.weatherCondition?.description?.text === 'string' ) out.condition = row.weatherCondition.description.text;
  if ( typeof row?.weatherCondition?.iconBaseUri === 'string' ) out.icon = row.weatherCondition.iconBaseUri;
  // Richer per-hour dimensions Google already returns - surfaced in the hourly detail panel.
  const humidity = n( row?.relativeHumidity );
  const dew = n( row?.dewPoint?.degrees );
  const heat = n( row?.heatIndex?.degrees );
  const chill = n( row?.windChill?.degrees );
  const wet = n( row?.wetBulbTemperature?.degrees );
  const gust = n( row?.wind?.gust?.value );
  const vis = n( row?.visibility?.distance );
  const pressure = n( row?.airPressure?.meanSeaLevelMillibars );
  const cloud = n( row?.cloudCover );
  const ice = n( row?.iceThickness?.thickness );
  if ( Number.isFinite( humidity ) ) out.humidity = Math.round( humidity );
  if ( Number.isFinite( dew ) ) out.dewPoint = Math.round( dew );
  if ( Number.isFinite( heat ) ) out.heatIndex = Math.round( heat );
  if ( Number.isFinite( chill ) ) out.windChill = Math.round( chill );
  if ( Number.isFinite( wet ) ) out.wetBulb = Math.round( wet );
  if ( Number.isFinite( gust ) ) out.windGust = Math.round( gust );
  if ( Number.isFinite( vis ) ) out.visibilityKm = vis;
  if ( Number.isFinite( pressure ) ) out.pressureHpa = Math.round( pressure );
  if ( Number.isFinite( cloud ) ) out.cloudCover = Math.round( cloud );
  if ( Number.isFinite( ice ) ) out.iceThicknessMm = ice;
  if ( typeof row?.precipitation?.probability?.type === 'string' ) out.precipitationType = row.precipitation.probability.type;
  return out;
}

export function airPointFromApi( row: Record<string, any> ): AirPoint | null {
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
    .filter( ( p: { code: string; value: number } ) => Boolean( p.code ) && Number.isFinite( p.value ) );
  const pm = pollutantRows.find( ( p: { code: string } ) => p.code === 'pm25' );
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

export function hourLabel( ms: number ): string {
  return new Intl.DateTimeFormat( 'en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric' } ).format( new Date( ms ) );
}

/* Readable label for the Weather days-forecast moonPhase enum (e.g. WAXING_CRESCENT ->
   "Waxing crescent"). Unlike the inline `.replace( /_/g, ' ' )` used for short precipitation/
   event enums, the moon phase is a full phrase, so it reads better in sentence case. */
export function moonPhaseLabel( value?: string ): string {
  if ( typeof value !== 'string' || !value.trim() ) return '';
  const words = value.trim().toLowerCase().replace( /_/g, ' ' );
  return words.charAt( 0 ).toUpperCase() + words.slice( 1 );
}

/* Friendly labels for the Google pollutant codes, shared by the pollutant rows and the
   dominant-pollutant chip so both read consistently (e.g. "pm25" -> "PM2.5"). */
export const POLLUTANT_LABELS: Record<string, string> = {
  pm25: 'PM2.5', pm10: 'PM10', no2: 'NO\u2082', o3: 'O\u2083', co: 'CO', so2: 'SO\u2082',
};

/* Resolve a dominant pollutant code to the same friendly label the rows use. Prefer a
   label already carried on a matching pollutant row, then the shared map, then fall back
   to the raw code so an unknown dominant pollutant is still surfaced rather than hidden. */
export function dominantPollutantLabel( code: string, pollutants: AirState['pollutants'] ): string {
  const fromRow = pollutants.find( p => p.code === code )?.label;
  return fromRow || POLLUTANT_LABELS[ code ] || code;
}

export function parseHealthRecommendations( raw: unknown ): AirState['healthRecommendations'] | undefined {
  if ( !raw || typeof raw !== 'object' ) return undefined;
  const source = raw as Record<string, unknown>;
  const out: Partial<Record<HealthRecommendationKey, string>> = {};
  HEALTH_PERSONAS.forEach( persona => {
    const value = source[ persona.apiKey ];
    if ( typeof value === 'string' && value.trim() ) out[ persona.apiKey ] = value.trim();
  } );
  return Object.keys( out ).length ? out : undefined;
}

export function timeZoneShortLabel( timeZoneId: string, timeZoneName: string ): string {
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

export function formatLocationClock( now: number, timeZoneId: string ): string {
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

export function formatLocationDate( now: number, timeZoneId: string ): string {
  const options: Intl.DateTimeFormatOptions = {
    timeZone: timeZoneId,
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  };
  try {
    return new Intl.DateTimeFormat( 'en-IN', options ).format( new Date( now ) );
  } catch {
    return new Intl.DateTimeFormat( 'en-IN', { ...options, timeZone: DEFAULT_LOCATION_TIME.timeZoneId } ).format( new Date( now ) );
  }
}

export function formatCurrencyValue( value: number, currency: string ): string {
  if ( !Number.isFinite( value ) ) return '';
  try {
    return new Intl.NumberFormat( 'en-IN', {
      style: 'currency',
      currency,
      maximumFractionDigits: Math.abs( value ) >= 100 ? 2 : 4,
    } ).format( value );
  } catch {
    return `${currency} ${value.toLocaleString( 'en-IN', { maximumFractionDigits: 4 } )}`;
  }
}

export function formatHistoryStamp( value: number, timeZoneId: string, zoneLabel: string ): string {
  try {
    const label = new Intl.DateTimeFormat( 'en-IN', {
      timeZone: timeZoneId,
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    } ).format( new Date( value ) );
    const zoneSuffix = zoneLabel.trim();
    return `${label}${zoneSuffix ? ` ${zoneSuffix}` : ''}`;
  } catch {
    return `${new Date( value ).toISOString().slice( 11, 16 )} UTC`;
  }
}

export function formatHistoryPointLabel( value: number, timeZoneId: string, zoneLabel: string ): string {
  try {
    const label = new Intl.DateTimeFormat( 'en-IN', {
      timeZone: timeZoneId,
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    } ).format( new Date( value ) );
    return `${label} ${zoneLabel}`;
  } catch {
    return `${new Date( value ).toISOString().slice( 11, 16 )} UTC`;
  }
}

/* Parse a currentConditions:lookup payload into the LEFT-card AirState (AQI value +
   category word + severity + pollutant rows + advisory). Returns null when no finite AQI
   arrived, so a point that fails to parse is DROPPED, never fabricated. Shared by the
   layer-activation center-point fetch; the grid points reuse airPointFromApi instead. */
export function airStateFromApiData( data: Record<string, any> | null | undefined ): AirState | null {
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
    // Prefer the band implied by Google's own category text so the colour matches the word;
    // fall back to the numeric CPCB threshold when the category is absent/unrecognised.
    sev: severityFromCategory( idx.category ) || cat.sev,
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
export function localAqiOverride( regionCode?: string ): Record<string, unknown> {
  return regionCode === 'IN'
    ? { customLocalAqis: [ { regionCode: 'IN', aqi: 'ind_cpcb' } ] }
    : {};
}

export function relativeAgeLabel( value?: string | number ): { label: string; stale: boolean } {
  if ( value === undefined || value === null ) return { label: 'Current', stale: false };
  const ms = typeof value === 'number' ? value : new Date( value ).getTime();
  if ( !Number.isFinite( ms ) ) return { label: 'Current', stale: false };
  const mins = Math.max( 0, Math.floor( ( Date.now() - ms ) / 60_000 ) );
  if ( mins < 1 ) return { label: 'Updated just now', stale: false };
  if ( mins < 60 ) return { label: `Updated ${mins} min ago`, stale: mins >= 30 };
  const hours = Math.floor( mins / 60 );
  return { label: `Updated ${hours} hr${hours === 1 ? '' : 's'} ago`, stale: true };
}

export function freshnessTimeLabel( label: string ): string {
  const clean = label.replace( /^Updated\s+/i, '' ).trim();
  return /^Current$/i.test( clean ) ? 'just now' : clean;
}

export const RECENT_PLACES_KEY = 'vayulok_recent_places_v2';

export function recentPlaces(): PlaceState[] {
  if ( typeof window === 'undefined' ) return [];
  try {
    const rows = JSON.parse( window.localStorage.getItem( RECENT_PLACES_KEY ) || '[]' );
    return Array.isArray( rows ) ? rows.slice( 0, 5 ) : [];
  } catch {
    return [];
  }
}

export function rememberPlace( place: PlaceState ) {
  if ( typeof window === 'undefined' ) return;
  try {
    const key = `${place.lat.toFixed( 4 )},${place.lng.toFixed( 4 )}`;
    const rows = recentPlaces().filter( p => `${p.lat.toFixed( 4 )},${p.lng.toFixed( 4 )}` !== key );
    rows.unshift( { name: place.name, addr: place.addr, lat: place.lat, lng: place.lng } );
    window.localStorage.setItem( RECENT_PLACES_KEY, JSON.stringify( rows.slice( 0, 5 ) ) );
  } catch { /* storage can be unavailable */ }
}
