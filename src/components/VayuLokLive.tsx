import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import VoiceSearchMic from './VoiceSearchMic';
import VayuLokWeatherInsights from './VayuLokWeatherInsights';
import {
  VayuLokCompactPill,
  VayuLokDataCard,
  VayuLokFreshnessStamp,
  VayuLokHorizontalRail,
  VayuLokIconAction,
  VayuLokUiStyles,
} from './VayuLokUiPrimitives';
import { API_BASE } from '../config/constants';

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
 * THE KEY. Read ONLY from process.env.NEXT_PUBLIC_GOOGLE_BROWSER_KEY, exactly as
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
 * MAP VISUALS. The keyed map paints Google's continuous AQI/PM2.5 heatmap tiles and the
 * documented Google US/EU precipitation tiles in Weather mode. Outside precipitation coverage,
 * the lightweight local atmospheric treatment supplies day/night sky and cloud/rain context from
 * the selected place's Google Weather values. The former Source Cooperative / NOAA GFS particle
 * layer was removed because it added a separate public-data transport, Zarr decoding and a
 * continuous canvas animation to the public page. VayuLok no longer mounts any non-Google map
 * data layer or deck.gl overlay.
 *
 * SELF-STYLING via styled-jsx with a vl-live- scope. styled-jsx only attaches its scoping
 * class to markup it can statically see, so every element stays INLINE in this component's
 * return tree. No bare html/body/* selectors; the mock's data-vl-preview-only block and
 * .vl-preview-shell are PREVIEW-ONLY and are NOT ported.
 */

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_BROWSER_KEY || '';

// Selected-place marker uses Google's canonical Material Symbols Outlined "location_on"
 // glyph (source: google/material-design-icons), presented on the same lime/green circle
 // as the site's icon system. This replaces the oversized bespoke teardrop marker.
const LOCATION_MARKER_ICON = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent( `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36"><circle cx="18" cy="18" r="17" fill="#d1f470"/><svg x="6" y="6" width="24" height="24" viewBox="0 -960 960 960"><path fill="#1a3a2a" d="M480-480q33 0 56.5-23.5T560-560q0-33-23.5-56.5T480-640q-33 0-56.5 23.5T400-560q0 33 23.5 56.5T480-480Zm0 294q122-112 181-203.5T720-552q0-109-69.5-178.5T480-800q-101 0-170.5 69.5T240-552q0 71 59 162.5T480-186Zm0 106Q319-217 239.5-334.5T160-552q0-150 96.5-239T480-880q127 0 223.5 89T800-552q0 100-79.5 217.5T480-80Zm0-480Z"/></svg></svg>` )}`;

const DOT_LINE_RGBA: [ number, number, number, number ] = [ 255, 255, 255, 230 ];

// Global map: do not re-introduce a lat/lng restriction here because destination search
// is worldwide. Manual pan/zoom gestures are disabled; only an explicit place selection
// is allowed to move the camera.

// Place-autocomplete debounce. 120ms is a deliberately snappy value: it keeps ONE
// Autocomplete Data API request per settled keystroke (so a fast typist does not spam the
// SKU) while feeling immediate rather than the previous 300ms lag. The session-token reuse
// (autocompleteTokenRef) behavior is unchanged; only the settle delay is shorter.
const SEARCH_DEBOUNCE_MS = 120;
const WORLD_SEARCH_DEBOUNCE_MS = 65;
const WORLD_SEARCH_MIN_CHARS = 2;
const FX_API_BASE = 'https://api.frankfurter.dev/v2';
const ROUTE_REQUEST_ENABLED = process.env.NEXT_PUBLIC_VAYULOK_ROUTE_ENABLED === 'true';
const FX_RATE_TTL_MS = 6 * 60 * 60 * 1000;

const FALLBACK_CURRENCY_CODES = [
  'USD', 'INR', 'EUR', 'GBP', 'AED', 'JPY', 'SGD', 'AUD', 'CAD', 'CHF',
  'CNY', 'KRW', 'THB', 'NZD', 'BRL', 'ZAR', 'SAR', 'IDR', 'MYR', 'HKD',
];

type CurrencySide = 'base' | 'quote';
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
const WEATHER_MAP_TILE_BASE = 'https://weather.googleapis.com/v1/mapTypes';
const US_PRECIPITATION_MAP_TYPE = 'US_PRECIPITATION_CURRENT';
const EU_PRECIPITATION_MAP_TYPE = 'EU_PRECIPITATION_CURRENT';
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
  placeId?: string;
  viewport?: { north: number; south: number; east: number; west: number };
  regionCode?: string;
}

interface SearchResult {
  name: string;
  addr: string;
  place?: PlaceState;
  prediction?: {
    placeId?: string;
    toPlace?: () => { id?: string };
  };
}

const DEFAULT_PLACE: PlaceState = {
  // India-first: match the hero globe's initial New Delhi selection. The detailed
  // map starts with a country-wide camera; a visitor's search or city choice
  // moves it to the requested location. No geolocation is inferred.
  name: 'New Delhi',
  addr: 'Delhi, India',
  lat: 28.6139,
  lng: 77.2090,
  regionCode: 'IN',
};

// Selected-place marker uses the current lime/green LOCATION_MARKER_ICON above. Keep this
// comment aligned with the actual marker options so future UI work does not "restore" a retired pin.

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

function airQualityCategoryLabel( word: string ): string {
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
function severityFromCategory( category?: string ): Sev | null {
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
function aqiBarClass( aqi: number ): string {
  return `vl-live-history-bar-${aqiCategory( aqi ).sev}`;
}

/* Human-readable label for the selected history range, used in the chart's aria-label so a
   screen reader hears "last 24 hours" rather than a raw hour count. */
function historyRangeLabel( hours: 24 | 168 ): string {
  return hours === 24 ? 'last 24 hours' : 'last 7 days';
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

const HEALTH_PERSONAS: HealthPersonaDefinition[] = [
  { id: 'general', label: 'General population', apiKey: 'generalPopulation', icon: 'general' },
  { id: 'elderly', label: 'Elderly', apiKey: 'elderly', icon: 'elderly' },
  { id: 'respiratory', label: 'Lung disease', apiKey: 'lungDiseasePopulation', icon: 'respiratory' },
  { id: 'heart', label: 'Heart disease', apiKey: 'heartDiseasePopulation', icon: 'heart' },
  { id: 'athletes', label: 'Athletes', apiKey: 'athletes', icon: 'athletes' },
  { id: 'pregnant', label: 'Pregnant women', apiKey: 'pregnantWomen', icon: 'pregnant' },
  { id: 'children', label: 'Children', apiKey: 'children', icon: 'children' },
];

function cleanAirInfo( value?: string ): string | undefined {
  if ( typeof value !== 'string' ) return undefined;
  const clean = value.replace( /\s+/g, ' ' ).trim();
  return clean || undefined;
}

function shortAirInfo( value?: string, max = 72 ): string | undefined {
  const clean = cleanAirInfo( value );
  if ( !clean ) return undefined;
  const firstSentence = clean.match( /^.*?[.!?](?:\s|$)/ )?.[ 0 ]?.trim();
  const candidate = firstSentence && firstSentence.length <= max ? firstSentence : clean;
  if ( candidate.length <= max ) return candidate;
  const clipped = candidate.slice( 0, Math.max( 1, max - 1 ) ).replace( /\s+\S*$/, '' ).trim();
  return `${clipped || candidate.slice( 0, Math.max( 1, max - 1 ) ).trim()}…`;
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
  source: 'default' | 'google' | 'fixed' | 'pending' | 'unavailable';
}

type UtilityPlaceSlot = 'world-from' | 'world-to' | 'route-from' | 'route-to';

interface RouteResultState {
  durationSeconds: number;
  distanceMeters: number;
  encodedPolyline?: string;
}

function directDistanceKm( from: PlaceState, to: PlaceState ): number {
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

function routeDurationLabel( seconds: number ): string {
  const totalMinutes = Math.max( 1, Math.round( seconds / 60 ) );
  const hours = Math.floor( totalMinutes / 60 );
  const minutes = totalMinutes % 60;
  if ( !hours ) return `${minutes} min`;
  if ( !minutes ) return `${hours} hr`;
  return `${hours} hr ${minutes} min`;
}

function routeDistanceLabel( meters: number ): string {
  if ( meters < 1000 ) return `${Math.max( 1, Math.round( meters ) )} m`;
  const km = meters / 1000;
  return `${km >= 100 ? Math.round( km ) : km.toFixed( 1 )} km`;
}

interface WorldTimeDestination {
  name: string;
  addr: string;
  lat: number;
  lng: number;
  regionCode?: string;
  time: LocationTimeState;
}

interface FxRateState {
  base: string;
  quote: string;
  rate: number;
  date: string;
  ts: number;
}

const DEFAULT_LOCATION_TIME: LocationTimeState = {
  timeZoneId: 'Asia/Kolkata',
  timeZoneName: 'India Standard Time',
  shortLabel: 'IST',
  source: 'default',
};
const PENDING_LOCATION_TIME: LocationTimeState = {
  timeZoneId: 'UTC', timeZoneName: '', shortLabel: 'UTC', source: 'pending',
};
const UNAVAILABLE_LOCATION_TIME: LocationTimeState = {
  timeZoneId: 'UTC', timeZoneName: '', shortLabel: 'UTC', source: 'unavailable',
};

const DEFAULT_WORLD_TIME_DESTINATION: WorldTimeDestination = {
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

interface WeatherState {
  temp?: number;
  feelsLike?: number;
  humidity?: number;
  windSpeed?: number;
  windUnit?: string;
  windDir?: string;
  windDeg?: number;
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
  // Added for the Weather tab: Google returns these on currentConditions and in its
  // currentConditionsHistory block (no extra API call needed).
  icon?: string;
  isDaytime?: boolean;
  windChill?: number;
  precipitationType?: string;
  temperatureChange?: number;
  dayMin?: number;
  dayMax?: number;
  recentQpf?: number;
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
  windDeg?: number;
  condition?: string;
  icon?: string;
  // Added for the hourly detail panel: the richer dimensions Google already returns per hour.
  humidity?: number;
  dewPoint?: number;
  heatIndex?: number;
  windChill?: number;
  wetBulb?: number;
  windGust?: number;
  visibilityKm?: number;
  pressureHpa?: number;
  cloudCover?: number;
  precipitationType?: string;
  iceThicknessMm?: number;
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
  // Added for the daily detail panel.
  nightCondition?: string;
  nightIcon?: string;
  dayDetails?: WeatherPeriodDetail;
  nightDetails?: WeatherPeriodDetail;
  feelsLikeMin?: number;
  feelsLikeMax?: number;
  humidity?: number;
  uv?: number;
  rainMm?: number;
  stormProb?: number;
  windSpeed?: number;
  windUnit?: string;
  windDir?: string;
  windGust?: number;
  precipitationType?: string;
  pressureHpa?: number;
  cloudCover?: number;
  visibilityKm?: number;
  heatIndex?: number;
  windChill?: number;
  iceThicknessMm?: number;
  moonrise?: string;
  moonset?: string;
  moonPhase?: string;
}
interface WeatherPeriodDetail {
  condition?: string;
  icon?: string;
  humidity?: number;
  uv?: number;
  rainProb?: number;
  rainMm?: number;
  stormProb?: number;
  windSpeed?: number;
  windUnit?: string;
  windDir?: string;
  windGust?: number;
  precipitationType?: string;
  pressureHpa?: number;
  cloudCover?: number;
  visibilityKm?: number;
  heatIndex?: number;
  windChill?: number;
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
  eventType?: string;
  description?: string;
  area?: string;
  polygon?: string;
  severity?: string;
  certainty?: string;
  urgency?: string;
  instruction?: string[];
  safetyRecommendations?: { directive: string; subtext?: string }[];
  startTime?: string;
  expires?: string;
  timezoneOffset?: string;
  // Google requires the originating authority to be attributed when an alert is shown.
  source?: string;
  sourcePublisher?: string;
  sourceUrl?: string;
}

// Google Weather publicAlerts coverage (Google Weather coverage page, checked 2026-10-12).
// Do not bill unsupported regions (including India); supported regions query live alerts.
const WEATHER_ALERT_REGION_CODES = new Set( [
  'AT','AU','BA','BE','BG','BR','CH','CI','CO','CY','CZ','DE','DK','EC','EE','ES','FI','FR',
  'GB','GH','GR','HR','HU','IE','IS','IT','JM','JP','KR','LT','LU','LV','MG','MK','MX','NL',
  'NO','NZ','PH','PL','PT','RO','RS','SB','SE','SG','SI','SK','TH','TW','US','VN',
] );

const COMPASS = [ 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW' ];
function windDirection( deg: number ): string {
  return COMPASS[ Math.round( deg / 45 ) % 8 ];
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

// Plain-language expansion of the short unit symbol, surfaced as a title/tooltip so a reader who
// does not know "ppb" or "µg/m³" can still understand the number. Keyed on the short symbol that
// concUnitLabel produces.
function unitTermLabel( unitSymbol: string ): string {
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
function formatPollutantValue( value: number ): string {
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

/* Readable label for the Weather days-forecast moonPhase enum (e.g. WAXING_CRESCENT ->
   "Waxing crescent"). Unlike the inline `.replace( /_/g, ' ' )` used for short precipitation/
   event enums, the moon phase is a full phrase, so it reads better in sentence case. */
function moonPhaseLabel( value?: string ): string {
  if ( typeof value !== 'string' || !value.trim() ) return '';
  const words = value.trim().toLowerCase().replace( /_/g, ' ' );
  return words.charAt( 0 ).toUpperCase() + words.slice( 1 );
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

function formatLocationDate( now: number, timeZoneId: string ): string {
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

function formatCurrencyValue( value: number, currency: string ): string {
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

function formatHistoryStamp( value: number, timeZoneId: string, zoneLabel: string ): string {
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

function formatHistoryPointLabel( value: number, timeZoneId: string, zoneLabel: string ): string {
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

function freshnessTimeLabel( label: string ): string {
  const clean = label.replace( /^Updated\s+/i, '' ).trim();
  return /^Current$/i.test( clean ) ? 'just now' : clean;
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

export interface VayuLokExternalLocation {
  name: string;
  addr?: string;
  lat: number;
  lng: number;
  regionCode?: string;
}

interface VayuLokLiveProps {
  mode?: 'air' | 'weather';
  onModeChange?: ( mode: 'air' | 'weather' ) => void;
  externalLocation?: VayuLokExternalLocation | null;
}

const VayuLokLive: React.FC<VayuLokLiveProps> = ( { mode = 'air', onModeChange, externalLocation = null } ) => {
  // Load the owner-selected local destination immediately so the map and live panels
  // are useful on first paint; search/recent-place selection replaces this destination.
  const [ place, setPlace ] = useState<PlaceState>( DEFAULT_PLACE );
  const [ hasSelection, setHasSelection ] = useState( true );
  const [ detailTab, setDetailTab ] = useState<'air' | 'weather'>( mode );
  const [ mapVisible, setMapVisible ] = useState( false );
  const [ mapReady, setMapReady ] = useState( false );
  const [ mapFailed, setMapFailed ] = useState( false );
  const [ searchStatus, setSearchStatus ] = useState<'idle' | 'searching' | 'no-results' | 'unavailable'>( 'idle' );

  const [ air, setAir ] = useState<AirState | null>( null );
  const [ weather, setWeather ] = useState<WeatherState | null>( null );
  const [ weatherHourly, setWeatherHourly ] = useState<WeatherHour[]>( [] );
  const [ weatherHistory, setWeatherHistory ] = useState<WeatherHour[]>( [] );
  const [ weatherDaily, setWeatherDaily ] = useState<WeatherDay[]>( [] );
  const [ weatherAlerts, setWeatherAlerts ] = useState<WeatherAlertRow[]>( [] );
  const [ weatherAlertStatus, setWeatherAlertStatus ] = useState<'idle' | 'loading' | 'active' | 'none' | 'unsupported' | 'error'>( 'idle' );
  const [ airForecast, setAirForecast ] = useState<AirPoint[]>( [] );
  const [ airForecastHours, setAirForecastHours ] = useState<24 | 48 | 96>( 24 );
  const [ airForecastInspectIdx, setAirForecastInspectIdx ] = useState( 0 );
  // Weather tab UI state: hourly range + inspected hour, inspected day, and the history metric.
  const [ weatherHours, setWeatherHours ] = useState<24 | 48 | 96>( 24 );
  const [ weatherHourInspectIdx, setWeatherHourInspectIdx ] = useState<number | null>( 0 );
  const [ weatherDayInspectIdx, setWeatherDayInspectIdx ] = useState<number | null>( null );
  const [ weatherDayPeriod, setWeatherDayPeriod ] = useState<'day' | 'night'>( 'day' );
  const [ weatherHistMetric, setWeatherHistMetric ] = useState<'temp' | 'rain' | 'humidity' | 'pressure' | 'wind' | 'cloud'>( 'temp' );
  const [ weatherHistoryInspectIdx, setWeatherHistoryInspectIdx ] = useState<number | null>( null );
  // Explicit Air-forecast state machine so the section can show loading skeletons, the real
  // strip, an honest "no rows" empty state, or a concise error - instead of silently rendering
  // nothing when the forecast:lookup request fails. 'idle' is the pre-selection resting state.
  const [ airForecastStatus, setAirForecastStatus ] = useState<'idle' | 'loading' | 'success' | 'empty' | 'error'>( 'idle' );
  const [ airHistory, setAirHistory ] = useState<AirPoint[]>( [] );
  // Start with 24h history for a lighter first load; 7d remains available on demand.
  // The 30-day/720 option stays removed from the UI.
  const [ historyRange, setHistoryRange ] = useState<24 | 168>( 24 );
  const [ historyLoading, setHistoryLoading ] = useState( false );
  const [ dataLoading, setDataLoading ] = useState( false );
  const [ coreError, setCoreError ] = useState( false );
  const [ refreshNonce, setRefreshNonce ] = useState( 0 );
  const [ coreFetchedAt, setCoreFetchedAt ] = useState<number | null>( null );
  const [ forecastFetchedAt, setForecastFetchedAt ] = useState<number | null>( null );
  const [ weatherHistoryFetchedAt, setWeatherHistoryFetchedAt ] = useState<number | null>( null );
  const [ mapCandidate, setMapCandidate ] = useState<PlaceState | null>( null );
  const [ addressDescriptor, setAddressDescriptor ] = useState( '' );
  const [ locationTime, setLocationTime ] = useState<LocationTimeState>( DEFAULT_LOCATION_TIME );
  // Static export and the first browser render must agree. Advance to the real clock immediately
  // after hydration; live time continues to refresh every 30 seconds.
  const [ clockNow, setClockNow ] = useState<number | null>( null );

  // Search combobox state.
  const [ query, setQuery ] = useState( '' );
  const [ results, setResults ] = useState<SearchResult[]>( [] );
  const [ open, setOpen ] = useState( false );
  const [ active, setActive ] = useState( -1 );

  // Useful tools use one Air/Weather-style card. Local time keeps two worldwide place searches;
  // Currency is intentionally lighter: just a searchable currency pair and its reference rate.
  const [ toolTab, setToolTab ] = useState<'time' | 'currency'>( 'time' );
  const [ utilityQueries, setUtilityQueries ] = useState<Record<UtilityPlaceSlot, string>>( {
    'world-from': '', 'world-to': '', 'route-from': '', 'route-to': '',
  } );
  const [ utilityResults, setUtilityResults ] = useState<SearchResult[]>( [] );
  const [ utilityOpenSlot, setUtilityOpenSlot ] = useState<UtilityPlaceSlot | null>( null );
  const [ utilityActive, setUtilityActive ] = useState( -1 );
  const [ utilitySearchStatus, setUtilitySearchStatus ] = useState<'idle' | 'searching' | 'no-results' | 'unavailable'>( 'idle' );
  const [ worldSource, setWorldSource ] = useState<WorldTimeDestination | null>( null );
  const [ worldDestination, setWorldDestination ] = useState<WorldTimeDestination>( DEFAULT_WORLD_TIME_DESTINATION );
  const [ routeFrom, setRouteFrom ] = useState<PlaceState | null>( null );
  const [ routeTo, setRouteTo ] = useState<PlaceState | null>( null );
  const [ routeResult, setRouteResult ] = useState<RouteResultState | null>( null );
  const [ routeLoading, setRouteLoading ] = useState( false );
  const [ routeError, setRouteError ] = useState( false );

  const [ fxBase, setFxBase ] = useState( 'USD' );
  const [ fxQuote, setFxQuote ] = useState( 'INR' );
  const [ fxBaseInput, setFxBaseInput ] = useState( 'USD' );
  const [ fxQuoteInput, setFxQuoteInput ] = useState( 'INR' );
  // Currency choices come from the rate provider itself when the Currency tab is opened.
  // The compact fallback list is provider-safe and keeps the control usable if that catalogue
  // request is temporarily unavailable. No browser-wide Intl catalogue is exposed.
  const [ currencyCodes, setCurrencyCodes ] = useState<string[]>( FALLBACK_CURRENCY_CODES );
  const [ currencyOpenSide, setCurrencyOpenSide ] = useState<CurrencySide | null>( null );
  const [ currencyActive, setCurrencyActive ] = useState( 0 );
  const currencyCodeSet = useMemo( () => new Set( currencyCodes ), [ currencyCodes ] );
  const [ fxRate, setFxRate ] = useState<FxRateState | null>( null );
  const [ fxLoading, setFxLoading ] = useState( false );
  const [ fxError, setFxError ] = useState( false );
  const [ deferredDataReady, setDeferredDataReady ] = useState( false );

  // Bumped by the map-failed "Try again" button to re-run the map init + timeout effects.
  const [ mapInitNonce, setMapInitNonce ] = useState( 0 );

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
  const [ pollutantTip, setPollutantTip ] = useState<{ code: string; top: number; left: number; side: 'left' | 'right' | 'top' | 'bottom' } | null>( null );
  // Touch/pointer/keyboard inspection is the Hourly History navigation; no separate arrow pager.
  const [ historyInspectIdx, setHistoryInspectIdx ] = useState<number | null>( null );

  const mapHost = useRef<HTMLDivElement | null>( null );
  const mapRef = useRef<unknown>( null );
  // Keep India's country-wide camera on first paint, instead of zooming straight
  // into the default city. Subsequent explicit selections still refocus the map.
  const framedPlaceRef = useRef<PlaceState | null>( DEFAULT_PLACE );
  // Bumped by every selection, map or search. A step that finishes later (a reverse geocode,
  // Place details) applies its result only if no newer selection has started since.
  const selectionSeqRef = useRef( 0 );
  const markerRef = useRef<unknown>( null );
  const markerCtorRef = useRef<( new ( opts: Record<string, unknown> ) => unknown ) | null>( null );
  const placesLibRef = useRef<Record<string, unknown> | null>( null );
  const autocompleteTokenRef = useRef<unknown>( null );
  const geocoder = useRef<unknown>( null );
  // Cache the last fetched values per "lat,lng" so re-selecting a place bills nothing.
  const cache = useRef<Record<string, { ts: number; air: AirState | null; weather: WeatherState | null }>>( {} );
  const forecastCache = useRef<Record<string, {
    airTs?: number;
    airHours?: 24 | 48 | 96;
    weatherTs?: number;
    hourly: WeatherHour[];
    daily: WeatherDay[];
    alerts: WeatherAlertRow[];
    alertStatus: 'idle' | 'loading' | 'active' | 'none' | 'unsupported' | 'error';
    airForecast: AirPoint[];
  }>>( {} );
  const historyCache = useRef<Record<string, { ts: number; points: AirPoint[] }>>( {} );
  const weatherHistoryCache = useRef<Record<string, { ts: number; rows: WeatherHour[] }>>( {} );
  const timeZoneCache = useRef<Record<string, LocationTimeState>>( {} );
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>( null );
  const utilitySearchTimer = useRef<ReturnType<typeof setTimeout> | null>( null );
  const utilitySearchSeqRef = useRef( 0 );
  const utilityAutocompleteTokenRef = useRef<unknown>( null );
  const fxRateCache = useRef<Record<string, FxRateState>>( {} );
  const fxRequestSeqRef = useRef( 0 );
  const currencyCatalogLoadedRef = useRef( false );
  // The google.maps.ImageMapType instance for the continuous AQI heatmap tile overlay
  // (FEAT-001). Attached by DEFAULT once the KEYED map is initialized (layer defaults to
  // 'AQI'), pushed onto map.overlayMapTypes, and detached idempotently on toggle-off /
  // switch-to-PM2.5 / unmount. On the keyless path it is NEVER constructed.
  //
  // NOTE: Google's heatmap MapType enum exposes global UAQI and PM2.5 plus regional AQI palettes;
  // it does NOT expose PM10/NO2/O3 pollutant heatmap tiles. Keep AQI + PM2.5 only rather than
  // inventing unsupported map types. The retired deck.gl and NOAA/Zarr paths are no longer part
  // of this component or its dependency tree.
  const airForecastStripRef = useRef<HTMLDivElement | null>( null );
  const healthRailRef = useRef<HTMLDivElement | null>( null );
  const heatmapOverlayRef = useRef<unknown>( null );
  const weatherOverlayRef = useRef<unknown>( null );
  const alertBoundaryFeaturesRef = useRef<unknown[]>( [] );
  const [ activeAlertBoundaryId, setActiveAlertBoundaryId ] = useState<string | null>( null );

  useEffect( () => {
    setClockNow( Date.now() );
    const timer = window.setInterval( () => setClockNow( Date.now() ), 30_000 );
    return () => window.clearInterval( timer );
  }, [] );

  // Keep first paint light. Forecast/history panels are below the immediate "Now" experience,
  // so start those larger requests only when the browser has breathing room.
  useEffect( () => {
    if ( typeof window === 'undefined' ) return;
    const idleWindow = window as typeof window & {
      requestIdleCallback?: ( cb: () => void, options?: { timeout?: number } ) => number;
      cancelIdleCallback?: ( id: number ) => void;
    };
    if ( idleWindow.requestIdleCallback ) {
      const id = idleWindow.requestIdleCallback( () => setDeferredDataReady( true ), { timeout: 1800 } );
      return () => idleWindow.cancelIdleCallback?.( id );
    }
    const id = window.setTimeout( () => setDeferredDataReady( true ), 450 );
    return () => window.clearTimeout( id );
  }, [] );

  useEffect( () => {
    setDetailTab( mode );
  }, [ mode ] );

  useEffect( () => {
    if ( !externalLocation || !Number.isFinite( externalLocation.lat ) || !Number.isFinite( externalLocation.lng ) ) return;
    const next: PlaceState = {
      name: externalLocation.name,
      addr: externalLocation.addr || externalLocation.name,
      lat: externalLocation.lat,
      lng: externalLocation.lng,
      ...( externalLocation.regionCode ? { regionCode: externalLocation.regionCode } : {} ),
    };
    ++selectionSeqRef.current;
    rememberPlace( next );
    setPlace( next );
    setHasSelection( true );
    setMapCandidate( null );
    setQuery( '' );
    setResults( [] );
    setOpen( false );
    setActive( -1 );
    setSearchStatus( 'idle' );
  }, [ externalLocation ] );

  // Reset inspected history only when its identity really changes. Resetting on every array
  // reference change races with a click that lands as an async history response settles.
  useEffect( () => {
    setHistoryInspectIdx( null );
  }, [ place.lat, place.lng, historyRange ] );

  useEffect( () => {
    setHistoryInspectIdx( current => (
      current != null && current >= airHistory.length ? null : current
    ) );
  }, [ airHistory.length ] );

  useEffect( () => {
    setWeatherHistoryInspectIdx( null );
  }, [ place.lat, place.lng ] );

  useEffect( () => {
    setWeatherHistoryInspectIdx( current => (
      current != null && current >= weatherHistory.length ? null : current
    ) );
  }, [ weatherHistory.length ] );

  useEffect( () => {
    setAirForecastInspectIdx( 0 );
  }, [ airForecast, airForecastHours ] );

  useEffect( () => {
    setWeatherHourInspectIdx( weatherHourly.length ? 0 : null );
  }, [ place.lat, place.lng, weatherHours, weatherHourly.length ] );

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

    const isIndia = ( place.regionCode || '' ).toUpperCase() === 'IN';
    // IST is an immediate truthful fallback only for Indian places.
    setLocationTime( isIndia ? DEFAULT_LOCATION_TIME : PENDING_LOCATION_TIME );
    const ac = new AbortController();
    const timestamp = Math.floor( Date.now() / 1000 );
    const params = new URLSearchParams( {
      location: `${place.lat},${place.lng}`,
      timestamp: String( timestamp ),
      key: MAPS_KEY,
    } );

    void fetch( `https://maps.googleapis.com/maps/api/timezone/json?${params.toString()}`, { signal: ac.signal, cache: 'no-store' } )
      .then( async res => res.ok ? res.json() : null )
      .then( data => {
        if ( ac.signal.aborted ) return;
        if ( data?.status !== 'OK' || typeof data?.timeZoneId !== 'string' ) {
          setLocationTime( isIndia ? DEFAULT_LOCATION_TIME : UNAVAILABLE_LOCATION_TIME );
          return;
        }
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
      .catch( () => {
        if ( !ac.signal.aborted ) setLocationTime( isIndia ? DEFAULT_LOCATION_TIME : UNAVAILABLE_LOCATION_TIME );
      } );

    return () => ac.abort();
  }, [ place.lat, place.lng, hasSelection ] );

  const openPollutantTip = useCallback( ( code: string, el: HTMLElement ) => {
    if ( typeof window === 'undefined' ) return;
    const rect = el.getBoundingClientRect();
    const gutter = 10;
    const gap = 10;
    const width = Math.min( 360, Math.max( 240, window.innerWidth - gutter * 2 ) );
    const estimatedHeight = Math.min( 320, Math.max( 160, window.innerHeight - gutter * 2 ) );
    const maxLeft = Math.max( gutter, window.innerWidth - width - gutter );
    const maxTop = Math.max( gutter, window.innerHeight - estimatedHeight - gutter );

    let viewportLeft: number;
    let viewportTop: number;
    let side: 'left' | 'right' | 'top' | 'bottom';

    if ( window.innerWidth <= 700 ) {
      const below = rect.bottom + gap;
      const canOpenBelow = below + estimatedHeight <= window.innerHeight - gutter;
      side = canOpenBelow ? 'bottom' : 'top';
      viewportLeft = clamp( rect.left + rect.width / 2 - width / 2, gutter, maxLeft );
      viewportTop = canOpenBelow
        ? clamp( below, gutter, maxTop )
        : clamp( rect.top - gap - estimatedHeight, gutter, maxTop );
    } else {
      const canOpenRight = rect.right + gap + width <= window.innerWidth - gutter;
      side = canOpenRight ? 'right' : 'left';
      viewportLeft = canOpenRight
        ? clamp( rect.right + gap, gutter, maxLeft )
        : clamp( rect.left - width - gap, gutter, maxLeft );
      viewportTop = clamp( rect.top - 16, gutter, maxTop );
    }

    setPollutantTip( {
      code,
      left: viewportLeft + window.scrollX,
      top: viewportTop + window.scrollY,
      side,
    } );
  }, [] );

  const clearAlertBoundary = useCallback( () => {
    const map = mapRef.current as { data?: { remove?: ( feature: unknown ) => void } } | null;
    if ( map?.data?.remove ) {
      alertBoundaryFeaturesRef.current.forEach( feature => map.data?.remove?.( feature ) );
    }
    alertBoundaryFeaturesRef.current = [];
    setActiveAlertBoundaryId( null );
  }, [] );

  const showAlertBoundary = useCallback( ( alert: WeatherAlertRow ) => {
    if ( !alert.polygon ) return;
    const map = mapRef.current as {
      data?: {
        addGeoJson?: ( geo: Record<string, unknown> ) => unknown[];
        setStyle?: ( style: Record<string, unknown> ) => void;
        remove?: ( feature: unknown ) => void;
      };
      fitBounds?: ( bounds: { north: number; south: number; east: number; west: number }, padding?: number ) => void;
    } | null;
    if ( !map?.data?.addGeoJson ) return;

    try {
      alertBoundaryFeaturesRef.current.forEach( feature => map.data?.remove?.( feature ) );
      const geometry = JSON.parse( alert.polygon ) as { type?: string; coordinates?: unknown };
      if ( !geometry || ![ 'Polygon', 'MultiPolygon', 'Feature' ].includes( String( geometry.type || '' ) ) ) return;
      const feature = geometry.type === 'Feature'
        ? geometry as unknown as Record<string, unknown>
        : { type: 'Feature', properties: { alertId: alert.id }, geometry };
      const added = map.data.addGeoJson( feature );
      alertBoundaryFeaturesRef.current = Array.isArray( added ) ? added : [];
      map.data.setStyle?.( {
        fillColor: '#d1f470',
        fillOpacity: .2,
        strokeColor: '#1a3a2a',
        strokeOpacity: .9,
        strokeWeight: 2,
      } );

      const points: [ number, number ][] = [];
      const walk = ( value: unknown ) => {
        if ( Array.isArray( value ) && value.length >= 2 && typeof value[ 0 ] === 'number' && typeof value[ 1 ] === 'number' ) {
          points.push( [ value[ 0 ], value[ 1 ] ] );
          return;
        }
        if ( Array.isArray( value ) ) value.forEach( walk );
      };
      walk( geometry.coordinates );
      if ( points.length && map.fitBounds ) {
        const lngs = points.map( point => point[ 0 ] );
        const lats = points.map( point => point[ 1 ] );
        map.fitBounds( {
          north: Math.max( ...lats ),
          south: Math.min( ...lats ),
          east: Math.max( ...lngs ),
          west: Math.min( ...lngs ),
        }, 36 );
      }
      setActiveAlertBoundaryId( alert.id );
    } catch {
      clearAlertBoundary();
    }
  }, [ clearAlertBoundary ] );

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
    clearAlertBoundary();
  }, [ place.lat, place.lng, clearAlertBoundary ] );

  useEffect( () => {
    if ( !MAPS_KEY || mapReady ) return;
    setMapFailed( false );
    const id = window.setTimeout( () => setMapFailed( true ), 12_000 );
    return () => window.clearTimeout( id );
  }, [ mapReady, mapInitNonce ] );

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
        // The global namespace can exist before the async loader has installed
        // importLibrary or the Map constructor. Returning that partial namespace
        // makes initialisation silently exit and leaves "Loading map…" visible.
        if ( g && ( typeof g.importLibrary === 'function' || typeof g.Map === 'function' ) ) return g;
        await new Promise( r => setTimeout( r, 100 ) );
      }
      const g = w.google?.maps;
      return g && ( typeof g.importLibrary === 'function' || typeof g.Map === 'function' ) ? g : null;
    };

    const init = async () => {
      const g = await waitForMaps();
      if ( cancelled || !g ) return;
      const host = await waitForHost();
      if ( cancelled || !host ) return;

      // WITH loading=async, the google.maps namespace can exist before the Map
      // constructor is populated. First paint imports ONLY the maps library.
      // Marker waits for tile readiness; Places waits for typing; Geocoding waits
      // for an actual suggestion selection. Fall back to a legacy Map constructor
      // only for older loaders that already populated it.
      type MapsCtors = {
        Map: new ( el: HTMLElement, opts: Record<string, unknown> ) => unknown;
      };
      // The maps library is the only library allowed on the critical map path.
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

      // FIRST PAINT: only the maps library is allowed to block map construction.
      // Marker, Places and Geocoding are optional for the initial canvas, so loading them
      // serially here made "Loading map…" last for three unrelated network round trips.
      const map = new MapCtor( host, {
        // Match the approved reference composition: India prominent, Himalaya/China above,
        // Arabian Sea + Bay of Bengal below. The map has worldwide data, but its camera is
        // destination-driven: only search/recent-place selection moves it.
        center: { lat: 22.9734, lng: 78.6569 },
        zoom: 4,
        mapTypeId: 'hybrid',
        // Static presentation map. Search/recent-place selection is the only camera-control
        // path; direct drag/pan, pinch/wheel zoom, double-click zoom and keyboard movement are off.
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

      // Show the Google canvas as soon as the Map constructor succeeds. Google paints
      // base tiles progressively, so keeping the canvas at opacity:0 until `tilesloaded`
      // made a healthy map look stuck on "Loading map…". `mapReady` remains the stricter
      // tile-confirmed signal used by overlays and the 12s bad-key watchdog.
      requestAnimationFrame( () => {
        if ( !cancelled ) setMapVisible( true );
      } );

      const motionListeners: { remove?: () => void }[] = [];

      // No optional Google library is prefetched here. Keeping marker/Places/Geocoding
      // off the critical path reduces JS/network work while the base map is painting.

      // No direct map-selection listeners: the canvas is intentionally non-interactive.
      // Search/recent-place selection owns all location and camera changes.

      // `tilesloaded` is now a HEALTH/READINESS signal, not a visibility gate. A refused
      // browser key can still construct a Map object while never delivering usable tiles;
      // keeping mapReady tied to this event preserves the existing 12s fallback watchdog.
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
    // Keep the bootstrap lean. Places/marker/geocoding are imported lazily after the map constructor.
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent( MAPS_KEY )}&loading=async&v=beta`;
    document.head.appendChild( script );
    // Start the same namespace-readiness path immediately; it will resolve once
    // the async loader exposes google.maps, without depending on a DOM load event.
    runInit();
    return () => {
      cancelled = true;
      ( mapHost.current as ( HTMLDivElement & { __vlCleanup?: () => void } ) | null )?.__vlCleanup?.();
    };
    // mapInitNonce lets the map-failed "Try again" button re-run initialisation.
  }, [ mapInitNonce ] );

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

    // Weather mode owns the visual map surface, so no AQI/PM2.5 tile can remain attached.
    if ( detailTab !== 'air' ) {
      detachHeatmap();
      requestAnimationFrame( () => { setDataLoading( false ); } );
      return;
    }

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
  }, [ layer, place, refreshNonce, mapReady, hasSelection, detailTab ] );


  /* ---------------------------------------------------------------------------------
     WEATHER MAP TILES. Google currently documents current precipitation tiles only for
     the United States and Europe. They are mounted lazily only while Weather is active;
     unsupported regions use the local Weather-data sky/cloud/wind visual below. */
  useEffect( () => {
    if ( !MAPS_KEY || !mapReady || !hasSelection || detailTab !== 'weather' || typeof window === 'undefined' ) return;
    const map = mapRef.current as { overlayMapTypes?: {
      getLength?: () => number;
      getAt?: ( i: number ) => unknown;
      removeAt?: ( i: number ) => unknown;
      push?: ( value: unknown ) => void;
      clear?: () => void;
    } } | null;
    const omt = map?.overlayMapTypes;
    if ( !map || !omt ) return;

    const detach = () => {
      const overlay = weatherOverlayRef.current;
      if ( !overlay ) return;
      if ( typeof omt.getLength === 'function' && typeof omt.getAt === 'function' && typeof omt.removeAt === 'function' ) {
        for ( let i = omt.getLength() - 1; i >= 0; i-- ) if ( omt.getAt( i ) === overlay ) omt.removeAt( i );
      } else {
        omt.clear?.();
      }
      weatherOverlayRef.current = null;
    };

    detach();

    const region = ( place.regionCode || '' ).toUpperCase();
    const inUsBounds = place.lat >= 18 && place.lat <= 72 && place.lng >= -170 && place.lng <= -50;
    const inEuBounds = place.lat >= 34 && place.lat <= 72 && place.lng >= -25 && place.lng <= 45;
    const mapType = region === 'US' || inUsBounds
      ? US_PRECIPITATION_MAP_TYPE
      : inEuBounds
        ? EU_PRECIPITATION_MAP_TYPE
        : null;
    if ( !mapType ) return undefined;

    const w = window as unknown as { google?: { maps?: {
      ImageMapType?: new ( opts: Record<string, unknown> ) => unknown;
      Size?: new ( width: number, height: number ) => unknown;
    } } };
    const gmaps = w.google?.maps;
    if ( !gmaps?.ImageMapType || !gmaps?.Size || !omt.push ) return undefined;

    const overlay = new gmaps.ImageMapType( {
      name: mapType === US_PRECIPITATION_MAP_TYPE ? 'vl-live-us-precipitation' : 'vl-live-eu-precipitation',
      tileSize: new gmaps.Size( 256, 256 ),
      minZoom: 0,
      maxZoom: 16,
      opacity: 0.66,
      getTileUrl: ( coord: { x: number; y: number }, zoom: number ): string =>
        `${WEATHER_MAP_TILE_BASE}/${mapType}/mapTiles/${zoom}/${coord.x}/${coord.y}?key=${encodeURIComponent( MAPS_KEY )}`,
    } );
    omt.push( overlay );
    weatherOverlayRef.current = overlay;
    return () => { detach(); };
  }, [ detailTab, mapReady, hasSelection, place.lat, place.lng, place.regionCode ] );

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
    const CORE_TTL_MS = 15 * 60 * 1000;
    if ( cached && Date.now() - cached.ts < CORE_TTL_MS ) {
      requestAnimationFrame( () => {
        setAir( cached.air );
        setWeather( cached.weather );
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
    const ac = new AbortController();
    const store: { air: AirState | null; weather: WeatherState | null } = {
      air: null, weather: null,
    };

    // AIR QUALITY - India SKU currentConditions:lookup, India local AQI preferred.
    const fetchAir = async () => {
      try {
        const res = await fetch(
          `https://airquality.googleapis.com/v1/currentConditions:lookup?key=${encodeURIComponent( MAPS_KEY )}`,
          {
            method: 'POST',
            signal: ac.signal,
            cache: 'no-store',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify( {
              location: { latitude: lat, longitude: lng },
              extraComputations: [
                'POLLUTANT_CONCENTRATION',
                'LOCAL_AQI',
                'HEALTH_RECOMMENDATIONS',
                'DOMINANT_POLLUTANT_CONCENTRATION',
                // Request Google's per-pollutant sources/effects strings so the info popover
                // on each pollutant row can show them.
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
          { signal: ac.signal, cache: 'no-store' },
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
        if ( Number.isFinite( windDeg ) ) {
          out.windDir = windDirection( windDeg );
          out.windDeg = ( ( windDeg % 360 ) + 360 ) % 360;
        }
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
        // Extra current fields Google already returns (no extra call).
        if ( typeof d?.weatherCondition?.iconBaseUri === 'string' ) out.icon = d.weatherCondition.iconBaseUri;
        if ( typeof d?.isDaytime === 'boolean' ) out.isDaytime = d.isDaytime;
        const chill = n( d?.windChill?.degrees );
        if ( Number.isFinite( chill ) ) out.windChill = Math.round( chill );
        if ( typeof d?.precipitation?.probability?.type === 'string' ) out.precipitationType = d.precipitation.probability.type;
        // currentConditionsHistory: recent 24h change, day min/max and accumulated precip -
        // returned on the same response, so no second request.
        const hist = d?.currentConditionsHistory;
        const tChange = n( hist?.temperatureChange?.degrees );
        const dMax = n( hist?.maxTemperature?.degrees );
        const dMin = n( hist?.minTemperature?.degrees );
        const qpf = n( hist?.qpf?.quantity );
        if ( Number.isFinite( tChange ) ) out.temperatureChange = Math.round( tChange * 10 ) / 10;
        if ( Number.isFinite( dMax ) ) out.dayMax = Math.round( dMax );
        if ( Number.isFinite( dMin ) ) out.dayMin = Math.round( dMin );
        if ( Number.isFinite( qpf ) ) out.recentQpf = qpf;
        // Only keep weather if at least one field arrived.
        if ( Object.keys( out ).length ) store.weather = out;
      } catch { /* silent degradation */ }
    };

    ( async () => {
      await Promise.all( [ fetchAir(), fetchWeather() ] );
      if ( ac.signal.aborted ) return;
      const fetchedAt = Date.now();
      cache.current[ cacheKey ] = { ts: fetchedAt, ...store };
      // First setState via rAF to avoid react-hooks/set-state-in-effect.
      requestAnimationFrame( () => {
        if ( ac.signal.aborted ) return;
        setAir( store.air );
        setWeather( store.weather );
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
    if ( !deferredDataReady || !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;
    const ac = new AbortController();
    const { lat, lng } = place;
    const forecastKey = `${lat.toFixed( 4 )},${lng.toFixed( 4 )}`;
    const cachedForecast = forecastCache.current[ forecastKey ];
    const FORECAST_TTL_MS = 30 * 60 * 1000;

    if (
      detailTab === 'air'
      && cachedForecast?.airTs
      && cachedForecast.airHours === airForecastHours
      && Date.now() - cachedForecast.airTs < FORECAST_TTL_MS
    ) {
      setAirForecast( cachedForecast.airForecast );
      setAirForecastStatus( cachedForecast.airForecast.length ? 'success' : 'empty' );
      setForecastFetchedAt( cachedForecast.airTs );
      return () => ac.abort();
    }
    if ( detailTab === 'weather' && cachedForecast?.weatherTs && Date.now() - cachedForecast.weatherTs < FORECAST_TTL_MS ) {
      setWeatherHourly( cachedForecast.hourly );
      setWeatherDaily( cachedForecast.daily );
      setWeatherAlerts( cachedForecast.alerts );
      setWeatherAlertStatus( cachedForecast.alertStatus );
      setForecastFetchedAt( cachedForecast.weatherTs );
      return () => ac.abort();
    }

    if ( detailTab === 'air' ) {
      setAirForecast( [] );
      setAirForecastStatus( 'loading' );
    } else {
      setWeatherHourly( [] );
      setWeatherDaily( [] );
      setWeatherAlerts( [] );
      setWeatherAlertStatus( 'loading' );
    }
    const forecastStore: {
      hourly: WeatherHour[];
      daily: WeatherDay[];
      alerts: WeatherAlertRow[];
      alertStatus: 'idle' | 'loading' | 'active' | 'none' | 'unsupported' | 'error';
      airForecast: AirPoint[];
    } = { hourly: [], daily: [], alerts: [], alertStatus: 'loading', airForecast: [] };

    const getJson = async ( url: string ) => {
      const res = await fetch( url, { signal: ac.signal, cache: 'no-store' } );
      if ( !res.ok ) return null;
      return res.json();
    };

    const loadHourly = async () => {
      const rows: WeatherHour[] = [];
      let pageToken = '';
      for ( let page = 0; page < 4 && !ac.signal.aborted; page++ ) {
        let url = 'https://weather.googleapis.com/v1/forecast/hours:lookup?key=' + encodeURIComponent( MAPS_KEY )
          + '&location.latitude=' + lat + '&location.longitude=' + lng
          + '&hours=96&pageSize=24&unitsSystem=METRIC&languageCode=en';
        if ( pageToken ) url += '&pageToken=' + encodeURIComponent( pageToken );
        const data = await getJson( url );
        if ( !data || ac.signal.aborted ) break;
        rows.push( ...( Array.isArray( data.forecastHours ) ? data.forecastHours : [] )
          .map( ( row: Record<string, any> ) => weatherHourFromApi( row ) )
          .filter( Boolean ) as WeatherHour[] );
        pageToken = typeof data.nextPageToken === 'string' ? data.nextPageToken : '';
        if ( !pageToken ) break;
      }
      forecastStore.hourly = rows.slice( 0, 96 );
      setWeatherHourly( rows.slice( 0, 96 ) );
    };

    const loadDaily = async () => {
      const url = 'https://weather.googleapis.com/v1/forecast/days:lookup?key=' + encodeURIComponent( MAPS_KEY )
        + '&location.latitude=' + lat + '&location.longitude=' + lng
        + '&days=10&pageSize=10&unitsSystem=METRIC&languageCode=en';
      const data = await getJson( url );
      if ( !data || ac.signal.aborted ) return;
      const rows: WeatherDay[] = ( Array.isArray( data.forecastDays ) ? data.forecastDays : [] ).map( ( row: any, i: number ) => {
        const d = row?.displayDate || {};
        const date = d?.year && d?.month && d?.day ? new Date( Date.UTC( d.year, d.month - 1, d.day ) ) : new Date();
        const day = row?.daytimeForecast || row?.nighttimeForecast || {};
        const night = row?.nighttimeForecast || {};

        const periodDetail = ( raw: any ): WeatherPeriodDetail => {
          const detail: WeatherPeriodDetail = {};
          if ( typeof raw?.weatherCondition?.description?.text === 'string' ) detail.condition = raw.weatherCondition.description.text;
          if ( typeof raw?.weatherCondition?.iconBaseUri === 'string' ) detail.icon = raw.weatherCondition.iconBaseUri;
          const humidity = n( raw?.relativeHumidity );
          const uv = n( raw?.uvIndex );
          const rainProb = n( raw?.precipitation?.probability?.percent );
          const rainMm = n( raw?.precipitation?.qpf?.quantity );
          const storm = n( raw?.thunderstormProbability );
          const windSpeed = n( raw?.wind?.speed?.value );
          const windDeg = n( raw?.wind?.direction?.degrees );
          const windGust = n( raw?.wind?.gust?.value );
          const pressure = n( raw?.airPressure?.meanSeaLevelMillibars );
          const cloud = n( raw?.cloudCover );
          const visibility = n( raw?.visibility?.distance );
          const heatIndex = n( raw?.heatIndex?.degrees );
          const windChill = n( raw?.windChill?.degrees );
          if ( Number.isFinite( humidity ) ) detail.humidity = Math.round( humidity );
          if ( Number.isFinite( uv ) ) detail.uv = Math.round( uv );
          if ( Number.isFinite( rainProb ) ) detail.rainProb = Math.round( rainProb );
          if ( Number.isFinite( rainMm ) ) detail.rainMm = rainMm;
          if ( Number.isFinite( storm ) ) detail.stormProb = Math.round( storm );
          if ( Number.isFinite( windSpeed ) ) {
            detail.windSpeed = Math.round( windSpeed );
            detail.windUnit = windUnitLabel( raw?.wind?.speed?.unit );
          }
          if ( Number.isFinite( windDeg ) ) detail.windDir = windDirection( windDeg );
          if ( Number.isFinite( windGust ) ) detail.windGust = Math.round( windGust );
          if ( Number.isFinite( pressure ) ) detail.pressureHpa = Math.round( pressure );
          if ( Number.isFinite( cloud ) ) detail.cloudCover = Math.round( cloud );
          if ( Number.isFinite( visibility ) ) detail.visibilityKm = visibility;
          if ( Number.isFinite( heatIndex ) ) detail.heatIndex = Math.round( heatIndex );
          if ( Number.isFinite( windChill ) ) detail.windChill = Math.round( windChill );
          if ( typeof raw?.precipitation?.probability?.type === 'string' ) detail.precipitationType = raw.precipitation.probability.type;
          return detail;
        };

        const dayDetails = periodDetail( day );
        const nightDetails = periodDetail( night );
        const min = n( row?.minTemperature?.degrees );
        const max = n( row?.maxTemperature?.degrees );
        const flMin = n( row?.feelsLikeMinTemperature?.degrees );
        const flMax = n( row?.feelsLikeMaxTemperature?.degrees );
        const ice = n( row?.iceThickness?.thickness ?? day?.iceThickness?.thickness ?? night?.iceThickness?.thickness );

        return {
          time: date.getTime(),
          label: i === 0 ? 'Today' : new Intl.DateTimeFormat( 'en-IN', { weekday: 'short', timeZone: 'UTC' } ).format( date ),
          dateLabel: new Intl.DateTimeFormat( 'en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' } ).format( date ),
          ...( Number.isFinite( min ) ? { min: Math.round( min ) } : {} ),
          ...( Number.isFinite( max ) ? { max: Math.round( max ) } : {} ),
          ...( Number.isFinite( dayDetails.rainProb ) ? { rainProb: dayDetails.rainProb } : {} ),
          ...( dayDetails.condition ? { condition: dayDetails.condition } : {} ),
          ...( dayDetails.icon ? { icon: dayDetails.icon } : {} ),
          ...( typeof row?.sunEvents?.sunriseTime === 'string' ? { sunrise: row.sunEvents.sunriseTime } : {} ),
          ...( typeof row?.sunEvents?.sunsetTime === 'string' ? { sunset: row.sunEvents.sunsetTime } : {} ),
          ...( nightDetails.condition ? { nightCondition: nightDetails.condition } : {} ),
          ...( nightDetails.icon ? { nightIcon: nightDetails.icon } : {} ),
          ...( Object.keys( dayDetails ).length ? { dayDetails } : {} ),
          ...( Object.keys( nightDetails ).length ? { nightDetails } : {} ),
          ...( Number.isFinite( flMin ) ? { feelsLikeMin: Math.round( flMin ) } : {} ),
          ...( Number.isFinite( flMax ) ? { feelsLikeMax: Math.round( flMax ) } : {} ),
          ...( Number.isFinite( ice ) ? { iceThicknessMm: ice } : {} ),
          ...( typeof row?.moonEvents?.moonriseTimes?.[ 0 ] === 'string' ? { moonrise: row.moonEvents.moonriseTimes[ 0 ] } : {} ),
          ...( typeof row?.moonEvents?.moonsetTimes?.[ 0 ] === 'string' ? { moonset: row.moonEvents.moonsetTimes[ 0 ] } : {} ),
          ...( typeof row?.moonEvents?.moonPhase === 'string' ? { moonPhase: row.moonEvents.moonPhase } : {} ),
        };
      } );
      forecastStore.daily = rows;
      setWeatherDaily( rows );
    };

    // Weather alerts remain browser-side. Unsupported regions (including India) do not bill Google.
    const loadAlerts = async () => {
      const regionCode = String( place.regionCode || '' ).toUpperCase();
      if ( !WEATHER_ALERT_REGION_CODES.has( regionCode ) ) {
        forecastStore.alertStatus = 'unsupported';
        setWeatherAlertStatus( 'unsupported' );
        return;
      }
      setWeatherAlertStatus( 'loading' );
      try {
        const url = 'https://weather.googleapis.com/v1/publicAlerts:lookup?key=' + encodeURIComponent( MAPS_KEY )
          + '&location.latitude=' + lat + '&location.longitude=' + lng + '&languageCode=en';
        const data = await getJson( url );
        if ( !data || ac.signal.aborted ) {
          forecastStore.alertStatus = 'error';
          if ( !ac.signal.aborted ) setWeatherAlertStatus( 'error' );
          return;
        }
        const rows: WeatherAlertRow[] = ( Array.isArray( data.weatherAlerts ) ? data.weatherAlerts : [] )
          .map( ( row: any ) => {
            const title = typeof row?.alertTitle?.text === 'string' ? row.alertTitle.text.trim() : '';
            const id = typeof row?.alertId === 'string' ? row.alertId : '';
            if ( !title || !id ) return null;
            const sourceName = typeof row?.dataSource?.name === 'string' ? row.dataSource.name.trim() : '';
            const sourcePublisher = typeof row?.dataSource?.publisher === 'string' ? row.dataSource.publisher.trim() : '';
            const instructions = Array.isArray( row?.instruction )
              ? row.instruction.filter( ( item: unknown ) => typeof item === 'string' && item.trim() ).map( ( item: string ) => item.trim() )
              : typeof row?.instruction === 'string' && row.instruction.trim() ? [ row.instruction.trim() ] : [];
            const recommendations = ( Array.isArray( row?.safetyRecommendations ) ? row.safetyRecommendations : [] )
              .map( ( item: any ) => {
                const directive = typeof item?.directive === 'string' ? item.directive.trim() : '';
                if ( !directive ) return null;
                return {
                  directive,
                  ...( typeof item?.subtext === 'string' && item.subtext.trim() ? { subtext: item.subtext.trim() } : {} ),
                };
              } )
              .filter( Boolean ) as { directive: string; subtext?: string }[];
            return {
              id,
              title,
              ...( typeof row?.eventType === 'string' ? { eventType: row.eventType } : {} ),
              ...( typeof row?.description === 'string' && row.description.trim() ? { description: row.description.trim() } : {} ),
              ...( typeof row?.areaName === 'string' && row.areaName.trim() ? { area: row.areaName.trim() } : {} ),
              ...( typeof row?.polygon === 'string' && row.polygon.trim() ? { polygon: row.polygon.trim() } : {} ),
              ...( typeof row?.severity === 'string' ? { severity: row.severity } : {} ),
              ...( typeof row?.certainty === 'string' ? { certainty: row.certainty } : {} ),
              ...( typeof row?.urgency === 'string' ? { urgency: row.urgency } : {} ),
              ...( instructions.length ? { instruction: instructions } : {} ),
              ...( recommendations.length ? { safetyRecommendations: recommendations } : {} ),
              ...( typeof row?.startTime === 'string' ? { startTime: row.startTime } : {} ),
              ...( typeof row?.expirationTime === 'string' ? { expires: row.expirationTime } : {} ),
              ...( typeof row?.timezoneOffset === 'string' ? { timezoneOffset: row.timezoneOffset } : {} ),
              ...( sourceName ? { source: sourceName } : {} ),
              ...( sourcePublisher ? { sourcePublisher } : {} ),
              ...( typeof row?.dataSource?.authorityUri === 'string' ? { sourceUrl: row.dataSource.authorityUri } : {} ),
            } as WeatherAlertRow;
          } )
          .filter( Boolean ) as WeatherAlertRow[];
        const status = rows.length ? 'active' : 'none';
        forecastStore.alerts = rows;
        forecastStore.alertStatus = status;
        setWeatherAlerts( rows );
        setWeatherAlertStatus( status );
      } catch {
        forecastStore.alertStatus = 'error';
        if ( !ac.signal.aborted ) setWeatherAlertStatus( 'error' );
      }
    };

    const loadAirForecast = async () => {
      try {
      const start = new Date();
      start.setUTCMinutes( 0, 0, 0 );
      start.setUTCHours( start.getUTCHours() + 1 );
      // Fetch only the range the visitor asked for. The API period is one hour shorter than
      // the row count (24 rows => 23h span, 96 rows => 95h span), which also avoids Google's
      // unsupported exact-96-hour boundary.
      const forecastSpanHours = airForecastHours - 1;
      const end = new Date( start.getTime() + forecastSpanHours * 60 * 60 * 1000 );
      const res = await fetch(
        'https://airquality.googleapis.com/v1/forecast:lookup?key=' + encodeURIComponent( MAPS_KEY ),
        {
          method: 'POST',
          signal: ac.signal,
          cache: 'no-store',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( {
            location: { latitude: lat, longitude: lng },
            period: { startTime: start.toISOString(), endTime: end.toISOString() },
            pageSize: airForecastHours,
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
      if ( ac.signal.aborted ) return;
      if ( !res.ok ) {
        // Surface the failure instead of silently rendering an empty section. Log enough
        // technical detail in development to identify an HTTP/API/key problem, but never the
        // key or raw response - the URL carries the key in its query string, so log status only.
        if ( process.env.NODE_ENV !== 'production' ) {
          // eslint-disable-next-line no-console
          console.error( `[VayuLok] air forecast:lookup failed - HTTP ${res.status} ${res.statusText}` );
        }
        setAirForecastStatus( 'error' );
        return;
      }
      const data = await res.json();
      const rows = ( Array.isArray( data.hourlyForecasts ) ? data.hourlyForecasts : [] )
        .map( ( row: Record<string, any> ) => airPointFromApi( row ) )
        .filter( Boolean ) as AirPoint[];
      forecastStore.airForecast = rows;
      setAirForecast( rows );
      // A valid 200 with zero usable rows is 'empty', not an error.
      setAirForecastStatus( rows.length ? 'success' : 'empty' );
      } catch ( err ) {
        // Network/transport/parse failure (an aborted request is normal teardown, not an error).
        if ( ac.signal.aborted ) return;
        if ( process.env.NODE_ENV !== 'production' ) {
          // eslint-disable-next-line no-console
          console.error( '[VayuLok] air forecast:lookup threw', err instanceof Error ? err.message : err );
        }
        setAirForecastStatus( 'error' );
      }
    };

    const tasks = detailTab === 'air'
      ? [ loadAirForecast() ]
      : [ loadHourly(), loadDaily(), loadAlerts() ];

    void Promise.allSettled( tasks ).then( () => {
      if ( ac.signal.aborted ) return;
      const fetchedAt = Date.now();
      const previous = forecastCache.current[ forecastKey ] || {
        hourly: [],
        daily: [],
        alerts: [],
        alertStatus: 'idle' as const,
        airForecast: [],
      };
      forecastCache.current[ forecastKey ] = detailTab === 'air'
        ? { ...previous, airTs: fetchedAt, airHours: airForecastHours, airForecast: forecastStore.airForecast }
        : {
            ...previous,
            weatherTs: fetchedAt,
            hourly: forecastStore.hourly,
            daily: forecastStore.daily,
            alerts: forecastStore.alerts,
            alertStatus: forecastStore.alertStatus,
          };
      setForecastFetchedAt( fetchedAt );
    } );
    return () => ac.abort();
  }, [ deferredDataReady, detailTab, place, hasSelection, airForecastHours ] );

  useEffect( () => {
    if ( !deferredDataReady || detailTab !== 'weather' || !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;
    const ac = new AbortController();
    const { lat, lng } = place;
    const historyKey = `${lat.toFixed( 4 )},${lng.toFixed( 4 )}`;
    const cached = weatherHistoryCache.current[ historyKey ];
    const WEATHER_HISTORY_TTL_MS = 6 * 60 * 60 * 1000;
    if ( cached && Date.now() - cached.ts < WEATHER_HISTORY_TTL_MS ) {
      setWeatherHistory( cached.rows );
      setWeatherHistoryFetchedAt( cached.rows[ cached.rows.length - 1 ]?.time || cached.ts );
      return () => ac.abort();
    }

    setWeatherHistory( [] );
    const run = async () => {
      try {
        const url = 'https://weather.googleapis.com/v1/history/hours:lookup?key=' + encodeURIComponent( MAPS_KEY )
          + '&location.latitude=' + lat + '&location.longitude=' + lng
          + '&hours=24&pageSize=24&unitsSystem=METRIC&languageCode=en';
        const res = await fetch( url, { signal: ac.signal, cache: 'no-store' } );
        if ( !res.ok || ac.signal.aborted ) return;
        const data = await res.json();
        const rows = ( Array.isArray( data.historyHours ) ? data.historyHours : [] )
          .map( ( row: Record<string, any> ) => weatherHourFromApi( row ) )
          .filter( Boolean ) as WeatherHour[];
        rows.sort( ( a, b ) => a.time - b.time );
        const latest = rows.slice( -24 );
        if ( !ac.signal.aborted ) {
          const fetchedAt = Date.now();
          weatherHistoryCache.current[ historyKey ] = { ts: fetchedAt, rows: latest };
          setWeatherHistory( latest );
          setWeatherHistoryFetchedAt( latest[ latest.length - 1 ]?.time || fetchedAt );
        }
      } catch { /* historical weather is optional */ }
    };
    void run();
    return () => ac.abort();
  }, [ deferredDataReady, detailTab, place, hasSelection ] );

  useEffect( () => {
    if ( !deferredDataReady || detailTab !== 'air' || !MAPS_KEY || !hasSelection || typeof window === 'undefined' ) return;
    const ac = new AbortController();
    const { lat, lng } = place;
    setHistoryInspectIdx( null );
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
          extraComputations: [
            'LOCAL_AQI',
            'POLLUTANT_CONCENTRATION',
            'DOMINANT_POLLUTANT_CONCENTRATION',
            'POLLUTANT_ADDITIONAL_INFO',
          ],
          languageCode: 'en',
        };
        if ( pageToken ) body.pageToken = pageToken;
        const res = await fetch(
          'https://airquality.googleapis.com/v1/history:lookup?key=' + encodeURIComponent( MAPS_KEY ),
          {
            method: 'POST',
            signal: ac.signal,
            cache: 'no-store',
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
  }, [ deferredDataReady, detailTab, place, historyRange, hasSelection ] );

  /* ---------------------------------------------------------------------------------
     RECENTRE the map + move the marker when the place changes (after the map exists).
     The marker library is deliberately imported only after base tiles are ready, so it
     never competes with first paint. */
  useEffect( () => {
    if ( !mapReady || !hasSelection || typeof window === 'undefined' ) return;
    let cancelled = false;

    const syncPlace = async () => {
      const w = window as unknown as { google?: { maps?: {
        importLibrary?: ( name: string ) => Promise<Record<string, unknown>>;
        Marker?: new ( opts: Record<string, unknown> ) => unknown;
      } } };
      const map = mapRef.current as {
        setCenter?: ( p: { lat: number; lng: number } ) => void;
        setZoom?: ( zoom: number ) => void;
        fitBounds?: ( bounds: { north: number; south: number; east: number; west: number }, padding?: number ) => void;
      } | null;
      if ( !map || !w.google?.maps ) return;

      if ( !markerRef.current ) {
        let MarkerCtor = markerCtorRef.current;
        if ( !MarkerCtor ) {
          try {
            const markerLib = w.google.maps.importLibrary
              ? await w.google.maps.importLibrary( 'marker' )
              : null;
            if ( cancelled ) return;
            MarkerCtor = ( markerLib as { Marker?: new ( opts: Record<string, unknown> ) => unknown } | null )?.Marker
              || w.google.maps.Marker
              || null;
            markerCtorRef.current = MarkerCtor;
          } catch {
            MarkerCtor = w.google.maps.Marker || null;
            markerCtorRef.current = MarkerCtor;
          }
        }
        if ( MarkerCtor && !cancelled ) {
          markerRef.current = new MarkerCtor( {
            position: { lat: place.lat, lng: place.lng },
            map,
            title: place.name,
            icon: LOCATION_MARKER_ICON,
          } );
        }
      }

      if ( cancelled ) return;
      const marker = markerRef.current as {
        setPosition?: ( p: { lat: number; lng: number } ) => void;
        setTitle?: ( t: string ) => void;
        setMap?: ( m: unknown ) => void;
      } | null;

      if ( place !== framedPlaceRef.current ) {
        // Search selection owns the camera; direct map interaction is disabled.
        if ( place.viewport && map.fitBounds ) map.fitBounds( place.viewport, 56 );
        else {
          map.setCenter?.( { lat: place.lat, lng: place.lng } );
          map.setZoom?.( 14 );
        }
        framedPlaceRef.current = place;
      }
      marker?.setMap?.( map );
      marker?.setPosition?.( { lat: place.lat, lng: place.lng } );
      marker?.setTitle?.( place.name );
    };

    void syncPlace();
    return () => { cancelled = true; };
  }, [ place, mapReady, hasSelection ] );

  /* ---------------------------------------------------------------------------------
     SEARCH - modern Places Autocomplete Data API with one session token per query/
     selection session. Places loads only after settled typing; Geocoding loads only
     after the visitor selects a suggestion. No Place Details fields are requested. */
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

  // Geocoding is intentionally lazy: it is not imported with the map or while typing.
  // It loads only after a suggestion is selected, then stays cached in geocoder.current.
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


  const runUtilityPlaceSearch = useCallback( async ( slot: UtilityPlaceSlot, text: string ) => {
    const seq = ++utilitySearchSeqRef.current;
    const input = text.trim();
    if ( !MAPS_KEY || input.length < WORLD_SEARCH_MIN_CHARS ) {
      setUtilityResults( [] );
      setUtilityOpenSlot( null );
      setUtilityActive( -1 );
      setUtilitySearchStatus( 'idle' );
      return;
    }

    // Keep ownership on the field that launched the request so searching/no-result/error status
    // is announced beside the correct control. aria-expanded remains tied to actual results.
    setUtilityResults( [] );
    setUtilityOpenSlot( slot );
    setUtilityActive( -1 );
    setUtilitySearchStatus( 'searching' );

    const lib = await ensurePlacesLibrary();
    if ( seq !== utilitySearchSeqRef.current ) return;
    const Auto = lib?.AutocompleteSuggestion as {
      fetchAutocompleteSuggestions?: ( req: Record<string, unknown> ) => Promise<{ suggestions?: unknown[] }>;
    } | undefined;
    const Token = lib?.AutocompleteSessionToken as ( new () => unknown ) | undefined;
    if ( !Auto?.fetchAutocompleteSuggestions || !Token ) {
      setUtilityResults( [] );
      setUtilityOpenSlot( slot );
      setUtilityActive( -1 );
      setUtilitySearchStatus( 'unavailable' );
      return;
    }
    try {
      if ( !utilityAutocompleteTokenRef.current ) utilityAutocompleteTokenRef.current = new Token();
      const out = await Auto.fetchAutocompleteSuggestions( {
        input,
        sessionToken: utilityAutocompleteTokenRef.current,
      } );
      if ( seq !== utilitySearchSeqRef.current ) return;
      const mapped: SearchResult[] = ( Array.isArray( out?.suggestions ) ? out.suggestions : [] )
        .map( suggestion => {
          const prediction = ( suggestion as { placePrediction?: SearchResult['prediction'] & {
            mainText?: { text?: string; toString?: () => string };
            secondaryText?: { text?: string; toString?: () => string };
            text?: { toString?: () => string };
          } } )?.placePrediction;
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
      setUtilityResults( mapped );
      setUtilityActive( mapped.length ? 0 : -1 );
      setUtilityOpenSlot( slot );
      setUtilitySearchStatus( mapped.length ? 'idle' : 'no-results' );
    } catch {
      if ( seq !== utilitySearchSeqRef.current ) return;
      utilityAutocompleteTokenRef.current = null;
      setUtilityResults( [] );
      setUtilityOpenSlot( slot );
      setUtilityActive( -1 );
      setUtilitySearchStatus( 'unavailable' );
    }
  }, [ ensurePlacesLibrary ] );

  const resolveUtilityPlace = useCallback( async ( result: SearchResult ): Promise<PlaceState | null> => {
    const gc = await ensureGeocoder();
    const geocode = gc?.geocode?.bind( gc );
    if ( !geocode ) return null;
    let placeId = result.prediction?.placeId;
    if ( !placeId ) {
      try { placeId = result.prediction?.toPlace?.()?.id; } catch { /* address fallback below */ }
    }
    return new Promise<PlaceState | null>( resolve => {
      geocode(
        placeId ? { placeId } : { address: result.addr || result.name },
        ( rows: unknown[] | null, status: string ) => {
          if ( status !== 'OK' || !Array.isArray( rows ) || !rows.length ) {
            resolve( null );
            return;
          }
          const row = rows[ 0 ] as {
            formatted_address?: string;
            place_id?: string;
            geometry?: { location?: { lat: () => number; lng: () => number } };
            address_components?: { types?: string[]; short_name?: string }[];
          };
          const lat = row.geometry?.location?.lat?.();
          const lng = row.geometry?.location?.lng?.();
          if ( !Number.isFinite( lat ) || !Number.isFinite( lng ) ) {
            resolve( null );
            return;
          }
          const country = row.address_components?.find( part => part.types?.includes( 'country' ) )?.short_name;
          resolve( {
            name: row.formatted_address?.split( ',' )[ 0 ] || result.name,
            addr: row.formatted_address || result.addr || result.name,
            lat: lat as number,
            lng: lng as number,
            ...( row.place_id ? { placeId: row.place_id } : {} ),
            ...( country ? { regionCode: country.toUpperCase() } : {} ),
          } );
        },
      );
    } );
  }, [ ensureGeocoder ] );

  const resolveUtilityTimeZone = useCallback( async ( resolved: PlaceState ): Promise<LocationTimeState | null> => {
    const cacheKey = `${resolved.lat.toFixed( 4 )},${resolved.lng.toFixed( 4 )}`;
    const cached = timeZoneCache.current[ cacheKey ];
    if ( cached ) return cached;
    const timestamp = Math.floor( Date.now() / 1000 );
    const params = new URLSearchParams( {
      location: `${resolved.lat},${resolved.lng}`,
      timestamp: String( timestamp ),
      key: MAPS_KEY,
    } );
    try {
      const response = await fetch( `https://maps.googleapis.com/maps/api/timezone/json?${params.toString()}`, { cache: 'no-store' } );
      const data = response.ok ? await response.json() : null;
      if ( data?.status !== 'OK' || typeof data?.timeZoneId !== 'string' ) return null;
      const timeZoneName = typeof data.timeZoneName === 'string' ? data.timeZoneName : data.timeZoneId;
      const zone: LocationTimeState = {
        timeZoneId: data.timeZoneId,
        timeZoneName,
        shortLabel: timeZoneShortLabel( data.timeZoneId, timeZoneName ),
        source: 'google',
      };
      timeZoneCache.current[ cacheKey ] = zone;
      return zone;
    } catch {
      return null;
    }
  }, [] );

  const onUtilityQueryChange = ( slot: UtilityPlaceSlot, value: string ) => {
    ++utilitySearchSeqRef.current;
    setUtilityQueries( current => ( { ...current, [ slot ]: value } ) );
    if ( utilitySearchTimer.current ) clearTimeout( utilitySearchTimer.current );
    const trimmed = value.trim();
    if ( trimmed.length < WORLD_SEARCH_MIN_CHARS ) {
      utilityAutocompleteTokenRef.current = null;
      setUtilityResults( [] );
      setUtilityOpenSlot( null );
      setUtilityActive( -1 );
      setUtilitySearchStatus( 'idle' );
      return;
    }
    utilitySearchTimer.current = setTimeout(
      () => { void runUtilityPlaceSearch( slot, value ); },
      WORLD_SEARCH_DEBOUNCE_MS,
    );
  };

  const loadFxRate = useCallback( async ( base: string, quote: string ) => {
    const pair = `${base}/${quote}`;
    if ( base === quote ) {
      const same: FxRateState = { base, quote, rate: 1, date: new Date().toISOString().slice( 0, 10 ), ts: Date.now() };
      fxRateCache.current[ pair ] = same;
      setFxRate( same );
      setFxError( false );
      return;
    }
    const cached = fxRateCache.current[ pair ];
    if ( cached && Date.now() - cached.ts < FX_RATE_TTL_MS ) {
      setFxRate( cached );
      setFxError( false );
      return;
    }
    const seq = ++fxRequestSeqRef.current;
    setFxLoading( true );
    setFxError( false );
    try {
      const response = await fetch(
        `${FX_API_BASE}/rate/${encodeURIComponent( base.toLowerCase() )}/${encodeURIComponent( quote.toLowerCase() )}`,
        { cache: 'no-store', headers: { Accept: 'application/json' } },
      );
      const data = response.ok ? await response.json() : null;
      const rate = Number( data?.rate );
      if ( !Number.isFinite( rate ) || rate <= 0 ) throw new Error( 'invalid rate' );
      const next: FxRateState = {
        base,
        quote,
        rate,
        date: typeof data?.date === 'string' ? data.date : new Date().toISOString().slice( 0, 10 ),
        ts: Date.now(),
      };
      fxRateCache.current[ pair ] = next;
      if ( seq === fxRequestSeqRef.current ) setFxRate( next );
    } catch {
      if ( seq === fxRequestSeqRef.current ) setFxError( true );
    } finally {
      if ( seq === fxRequestSeqRef.current ) setFxLoading( false );
    }
  }, [] );

  useEffect( () => {
    if ( toolTab !== 'currency' ) return;
    void loadFxRate( fxBase, fxQuote );
  }, [ toolTab, fxBase, fxQuote, loadFxRate ] );

  useEffect( () => {
    if ( toolTab !== 'currency' || currencyCatalogLoadedRef.current ) return;
    currencyCatalogLoadedRef.current = true;
    void fetch( `${FX_API_BASE}/currencies`, {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    } )
      .then( async response => response.ok ? response.json() : null )
      .then( data => {
        const rows = Array.isArray( data ) ? data : [];
        const codes = rows
          .map( row => typeof row?.iso_code === 'string' ? row.iso_code.toUpperCase() : '' )
          .filter( code => /^[A-Z]{3}$/.test( code ) );
        if ( !codes.length ) {
          currencyCatalogLoadedRef.current = false;
          return;
        }
        const preferred = [ 'USD', 'INR' ];
        const seen = new Set<string>();
        const ordered = [ ...preferred, ...codes ].filter( code => codes.includes( code ) && !seen.has( code ) && seen.add( code ) );
        setCurrencyCodes( ordered );
      } )
      .catch( () => {
        currencyCatalogLoadedRef.current = false;
      } );
  }, [ toolTab ] );


  const chooseUtilityPlace = useCallback( async ( slot: UtilityPlaceSlot, result: SearchResult ) => {
    ++utilitySearchSeqRef.current;
    const resolved = await resolveUtilityPlace( result );
    if ( !resolved ) {
      setUtilitySearchStatus( 'unavailable' );
      return;
    }

    if ( slot === 'route-from' || slot === 'route-to' ) {
      if ( slot === 'route-from' ) setRouteFrom( resolved );
      else setRouteTo( resolved );
      setRouteResult( null );
      setRouteError( false );
      setUtilityQueries( current => ( { ...current, [ slot ]: '' } ) );
      setUtilityResults( [] );
      setUtilityOpenSlot( null );
      setUtilityActive( -1 );
      setUtilitySearchStatus( 'idle' );
      utilityAutocompleteTokenRef.current = null;
      return;
    }

    const zone = await resolveUtilityTimeZone( resolved );
    if ( !zone ) {
      setUtilitySearchStatus( 'unavailable' );
      return;
    }
    const worldPlace: WorldTimeDestination = {
      name: resolved.name,
      addr: resolved.addr,
      lat: resolved.lat,
      lng: resolved.lng,
      ...( resolved.regionCode ? { regionCode: resolved.regionCode } : {} ),
      time: zone,
    };
    if ( slot === 'world-from' ) setWorldSource( worldPlace );
    else setWorldDestination( worldPlace );

    setUtilityQueries( current => ( { ...current, [ slot ]: '' } ) );
    setUtilityResults( [] );
    setUtilityOpenSlot( null );
    setUtilityActive( -1 );
    setUtilitySearchStatus( 'idle' );
    utilityAutocompleteTokenRef.current = null;
  }, [ resolveUtilityPlace, resolveUtilityTimeZone ] );

  const onUtilityKeyDown = ( slot: UtilityPlaceSlot, e: React.KeyboardEvent<HTMLInputElement> ) => {
    if ( e.key === 'Escape' ) {
      ++utilitySearchSeqRef.current;
      setUtilityOpenSlot( null );
      setUtilitySearchStatus( 'idle' );
      return;
    }
    if ( utilityOpenSlot !== slot || !utilityResults.length ) return;
    if ( e.key === 'ArrowDown' ) {
      e.preventDefault();
      setUtilityActive( index => Math.min( index + 1, utilityResults.length - 1 ) );
    } else if ( e.key === 'ArrowUp' ) {
      e.preventDefault();
      setUtilityActive( index => Math.max( 0, index - 1 ) );
    } else if ( e.key === 'Enter' && utilityActive >= 0 ) {
      e.preventDefault();
      void chooseUtilityPlace( slot, utilityResults[ utilityActive ] );
    }
  };

  const onUtilityVoice = ( slot: UtilityPlaceSlot, transcript: string ) => {
    if ( utilitySearchTimer.current ) clearTimeout( utilitySearchTimer.current );
    utilityAutocompleteTokenRef.current = null;
    setUtilityQueries( current => ( { ...current, [ slot ]: transcript } ) );
    void runUtilityPlaceSearch( slot, transcript );
  };

  const swapRoutePlaces = () => {
    const nextFrom = routeTo;
    const nextTo = routeFrom;
    setRouteFrom( nextFrom );
    setRouteTo( nextTo );
    setRouteResult( null );
    setRouteError( false );
  };

  const checkRoute = async () => {
    if ( !ROUTE_REQUEST_ENABLED || !routeFrom || !routeTo || routeLoading ) return;
    setRouteLoading( true );
    setRouteError( false );
    setRouteResult( null );
    try {
      const response = await fetch( `${API_BASE}/vayulok/environment`, {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( {
          operation: 'route_drive',
          originLatitude: routeFrom.lat,
          originLongitude: routeFrom.lng,
          destinationLatitude: routeTo.lat,
          destinationLongitude: routeTo.lng,
        } ),
      } );
      const data = response.ok ? await response.json() : null;
      const row = Array.isArray( data?.routes ) ? data.routes[ 0 ] : null;
      const distanceMeters = Number( row?.distanceMeters );
      const durationText = typeof row?.duration === 'string' ? row.duration : '';
      const durationSeconds = Number( durationText.replace( /s$/, '' ) );
      if ( !Number.isFinite( distanceMeters ) || !Number.isFinite( durationSeconds ) ) throw new Error( 'invalid route' );
      setRouteResult( {
        distanceMeters,
        durationSeconds,
        ...( typeof row?.polyline?.encodedPolyline === 'string' ? { encodedPolyline: row.polyline.encodedPolyline } : {} ),
      } );
    } catch {
      setRouteError( true );
    } finally {
      setRouteLoading( false );
    }
  };

  const swapFxPair = () => {
    const nextBase = fxQuote;
    const nextQuote = fxBase;
    setFxBase( nextBase );
    setFxQuote( nextQuote );
    setFxBaseInput( nextBase );
    setFxQuoteInput( nextQuote );
    if ( fxRate && fxRate.base === fxBase && fxRate.quote === fxQuote && fxRate.rate > 0 ) {
      const reciprocal: FxRateState = {
        base: nextBase,
        quote: nextQuote,
        rate: 1 / fxRate.rate,
        date: fxRate.date,
        ts: Date.now(),
      };
      fxRateCache.current[ `${nextBase}/${nextQuote}` ] = reciprocal;
      setFxRate( reciprocal );
      setFxError( false );
    } else {
      void loadFxRate( nextBase, nextQuote );
    }
  };

  const currencySuggestions = useMemo( () => {
    if ( !currencyOpenSide ) return [];
    const input = ( currencyOpenSide === 'base' ? fxBaseInput : fxQuoteInput ).trim().toUpperCase();
    const committed = currencyOpenSide === 'base' ? fxBase : fxQuote;
    const other = currencyOpenSide === 'base' ? fxQuote : fxBase;
    const query = input === committed ? '' : input;
    const matches = currencyCodes.filter( code =>
      code !== other && ( !query || code.startsWith( query ) || code.includes( query ) ),
    );
    if ( !query && matches.includes( committed ) ) {
      return [ committed, ...matches.filter( code => code !== committed ) ].slice( 0, 8 );
    }
    return matches.slice( 0, 8 );
  }, [ currencyOpenSide, currencyCodes, fxBase, fxBaseInput, fxQuote, fxQuoteInput ] );

  const chooseCurrency = ( side: CurrencySide, code: string ) => {
    if ( !currencyCodeSet.has( code ) ) return;
    if ( side === 'base' ) {
      setFxBase( code );
      setFxBaseInput( code );
    } else {
      setFxQuote( code );
      setFxQuoteInput( code );
    }
    setFxRate( null );
    setCurrencyOpenSide( null );
    setCurrencyActive( 0 );
  };

  const onCurrencyInputChange = ( side: CurrencySide, value: string ) => {
    const normalized = value.toUpperCase().replace( /[^A-Z]/g, '' ).slice( 0, 3 );
    if ( side === 'base' ) setFxBaseInput( normalized );
    else setFxQuoteInput( normalized );
    setCurrencyOpenSide( side );
    setCurrencyActive( 0 );
  };

  const normalizeCurrencyInput = ( side: CurrencySide ) => {
    const input = side === 'base' ? fxBaseInput : fxQuoteInput;
    if ( currencyCodeSet.has( input ) ) {
      chooseCurrency( side, input );
      return;
    }
    if ( side === 'base' ) setFxBaseInput( fxBase );
    else setFxQuoteInput( fxQuote );
    setCurrencyOpenSide( null );
    setCurrencyActive( 0 );
  };

  const onCurrencyKeyDown = ( side: CurrencySide, e: React.KeyboardEvent<HTMLInputElement> ) => {
    if ( e.key === 'Escape' ) {
      e.preventDefault();
      if ( side === 'base' ) setFxBaseInput( fxBase );
      else setFxQuoteInput( fxQuote );
      setCurrencyOpenSide( null );
      setCurrencyActive( 0 );
      return;
    }
    if ( !currencySuggestions.length ) return;
    if ( e.key === 'ArrowDown' ) {
      e.preventDefault();
      setCurrencyActive( index => Math.min( index + 1, currencySuggestions.length - 1 ) );
    } else if ( e.key === 'ArrowUp' ) {
      e.preventDefault();
      setCurrencyActive( index => Math.max( 0, index - 1 ) );
    } else if ( e.key === 'Enter' ) {
      e.preventDefault();
      chooseCurrency( side, currencySuggestions[ currencyActive ] );
    }
  };

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

    if ( !Auto?.fetchAutocompleteSuggestions || !Token ) {
      setResults( [] );
      setOpen( false );
      setSearchStatus( 'unavailable' );
      return;
    }

    try {
      if ( !autocompleteTokenRef.current ) autocompleteTokenRef.current = new Token();
      const out = await Auto.fetchAutocompleteSuggestions( {
        input: text,
        sessionToken: autocompleteTokenRef.current,
      } );
      const mapped: SearchResult[] = ( Array.isArray( out?.suggestions ) ? out.suggestions : [] )
        .map( suggestion => {
          const prediction = ( suggestion as { placePrediction?: SearchResult['prediction'] & {
            mainText?: { text?: string; toString?: () => string };
            secondaryText?: { text?: string; toString?: () => string };
            text?: { toString?: () => string };
          } } )?.placePrediction;
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
      setOpen( mapped.length > 0 );
      setSearchStatus( mapped.length ? 'idle' : 'no-results' );
    } catch {
      autocompleteTokenRef.current = null;
      setResults( [] );
      setOpen( false );
      setSearchStatus( 'unavailable' );
    }
  }, [ ensurePlacesLibrary ] );


  const onQueryChange = ( e: React.ChangeEvent<HTMLInputElement> ) => {
    const v = e.target.value;
    setQuery( v );
    if ( searchTimer.current ) clearTimeout( searchTimer.current );
    if ( !v.trim() ) {
      autocompleteTokenRef.current = null;
      setResults( [] );
      setActive( -1 );
      setOpen( false );
      setSearchStatus( 'idle' );
      return;
    }
    // SEARCH_DEBOUNCE_MS (120ms) keeps one request per settled keystroke while feeling instant.
    searchTimer.current = setTimeout( () => { void runSearch( v ); }, SEARCH_DEBOUNCE_MS );
  };

  const choose = useCallback( async ( r: SearchResult ) => {
    const seq = ++selectionSeqRef.current;
    let next = r.place;

    if ( !next ) {
      const gc = await ensureGeocoder();
      const geocode = gc?.geocode?.bind( gc );
      if ( !geocode ) {
        setSearchStatus( 'unavailable' );
        return;
      }
      let placeId = r.prediction?.placeId;
      if ( !placeId ) {
        try { placeId = r.prediction?.toPlace?.()?.id; } catch { /* address fallback below */ }
      }
      next = await new Promise<PlaceState | undefined>( resolve => {
        geocode(
          placeId ? { placeId } : { address: r.addr || r.name },
          ( rows: unknown[] | null, status: string ) => {
            if ( status !== 'OK' || !Array.isArray( rows ) || !rows.length ) {
              resolve( undefined );
              return;
            }
            const row = rows[ 0 ] as {
              formatted_address?: string;
              place_id?: string;
              geometry?: {
                location?: { lat: () => number; lng: () => number };
                viewport?: { toJSON?: () => { north: number; south: number; east: number; west: number } };
              };
              address_components?: { types?: string[]; short_name?: string }[];
            };
            const lat = row.geometry?.location?.lat?.();
            const lng = row.geometry?.location?.lng?.();
            if ( !Number.isFinite( lat ) || !Number.isFinite( lng ) ) {
              resolve( undefined );
              return;
            }
            const country = row.address_components?.find( c => c.types?.includes( 'country' ) )?.short_name;
            const viewport = row.geometry?.viewport?.toJSON?.();
            resolve( {
              name: row.formatted_address?.split( ',' )[ 0 ] || r.name,
              addr: row.formatted_address || r.addr || r.name,
              lat: lat as number,
              lng: lng as number,
              ...( row.place_id ? { placeId: row.place_id } : {} ),
              ...( viewport && [ viewport.north, viewport.south, viewport.east, viewport.west ].every( Number.isFinite ) ? { viewport } : {} ),
              ...( country ? { regionCode: country.toUpperCase() } : {} ),
            } );
          },
        );
      } );
      autocompleteTokenRef.current = null;
    }

    if ( !next || seq !== selectionSeqRef.current ) {
      setSearchStatus( 'unavailable' );
      return;
    }
    rememberPlace( next );
    setPlace( next );
    setHasSelection( true );
    setMapCandidate( null );
    // Search is an action, not a second location display. The committed place is
    // already shown in the existing location/date/time context row.
    setQuery( '' );
    setOpen( false );
    setResults( [] );
    setActive( -1 );
    setSearchStatus( 'idle' );
  }, [ ensureGeocoder ] );

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

  useEffect( () => () => {
    if ( searchTimer.current ) clearTimeout( searchTimer.current );
    if ( utilitySearchTimer.current ) clearTimeout( utilitySearchTimer.current );
  }, [] );

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
  const regionalWeatherMapType = useMemo( () => {
    const region = ( place.regionCode || '' ).toUpperCase();
    if ( region === 'US' || ( place.lat >= 18 && place.lat <= 72 && place.lng >= -170 && place.lng <= -50 ) ) return US_PRECIPITATION_MAP_TYPE;
    if ( place.lat >= 34 && place.lat <= 72 && place.lng >= -25 && place.lng <= 45 ) return EU_PRECIPITATION_MAP_TYPE;
    return null;
  }, [ place.lat, place.lng, place.regionCode ] );
  const weatherVisual = useMemo( () => {
    if ( !weather || regionalWeatherMapType ) return null;
    const clamp = ( value: number, min: number, max: number ) => Math.min( max, Math.max( min, value ) );
    const cloud = clamp( Number.isFinite( weather.cloudCover ) ? weather.cloudCover as number : 0, 0, 100 );
    const rain = clamp( Number.isFinite( weather.rainProb ) ? weather.rainProb as number : 0, 0, 100 );
    const condition = ( weather.condition || '' ).toLowerCase();
    const rainy = rain >= 35 || ( Number.isFinite( weather.rainMm ) && ( weather.rainMm as number ) > 0.1 ) || /rain|drizzle|shower|storm/.test( condition );
    const cloudy = cloud >= 45 || /cloud|overcast|fog|mist|haze/.test( condition );
    return {
      className: [ weather.isDaytime === false ? 'is-night' : 'is-day', cloudy ? 'is-cloudy' : '', rainy ? 'is-rainy' : '' ].filter( Boolean ).join( ' ' ),
      skyOpacity: clamp( 0.18 + cloud * 0.0018 + rain * 0.0012, 0.18, 0.58 ),
      cloudOpacity: clamp( 0.08 + cloud * 0.0045, 0.08, 0.52 ),
    };
  }, [ weather, regionalWeatherMapType ] );



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
  const locationZoneReady = locationTime.source === 'google'
    || locationTime.source === 'fixed'
    || ( locationTime.source === 'default' && ( place.regionCode || 'IN' ).toUpperCase() === 'IN' );
  const locationTimeReady = clockNow != null && locationZoneReady;
  const locationClock = locationTimeReady && clockNow != null ? formatLocationClock( clockNow, locationTime.timeZoneId ) : '';
  const locationZoneLabel = locationZoneReady ? locationTime.shortLabel : '';
  const displayTimeZoneId = locationZoneReady ? locationTime.timeZoneId : 'UTC';
  const airAge = air?.updatedAt ? relativeAgeLabel( air.updatedAt ) : null;
  const weatherAge = weather?.currentTime || coreFetchedAt
    ? relativeAgeLabel( weather?.currentTime || coreFetchedAt || undefined )
    : null;
  const aqiScaleLabel = air?.indexName?.trim()
    || ( air?.indexCode === 'uaqi' ? 'Universal AQI' : 'AQI' );

  const currentWorldDestination: WorldTimeDestination = {
    name: place.name,
    addr: place.addr,
    lat: place.lat,
    lng: place.lng,
    ...( place.regionCode ? { regionCode: place.regionCode } : {} ),
    time: locationTime,
  };
  const effectiveWorldSource = worldSource || currentWorldDestination;
  const worldFrom = {
    name: effectiveWorldSource.name,
    addr: effectiveWorldSource.addr,
    clock: clockNow == null
      ? ''
      : effectiveWorldSource.time.source === 'pending' || effectiveWorldSource.time.source === 'unavailable'
        ? 'Unavailable'
        : formatLocationClock( clockNow, effectiveWorldSource.time.timeZoneId ),
    date: clockNow == null || effectiveWorldSource.time.source === 'pending' || effectiveWorldSource.time.source === 'unavailable'
      ? ''
      : formatLocationDate( clockNow, effectiveWorldSource.time.timeZoneId ),
    zone: effectiveWorldSource.time.source === 'pending' || effectiveWorldSource.time.source === 'unavailable'
      ? 'Local time'
      : timeZoneShortLabel( effectiveWorldSource.time.timeZoneId, effectiveWorldSource.time.timeZoneName ),
  };
  const worldTo = {
    name: worldDestination.name,
    addr: worldDestination.addr,
    clock: clockNow == null ? '' : formatLocationClock( clockNow, worldDestination.time.timeZoneId ),
    date: clockNow == null ? '' : formatLocationDate( clockNow, worldDestination.time.timeZoneId ),
    zone: timeZoneShortLabel( worldDestination.time.timeZoneId, worldDestination.time.timeZoneName ),
  };
  const swapWorldPlaces = () => {
    setWorldSource( worldDestination );
    setWorldDestination( effectiveWorldSource );
  };

  return (
    <section className="vl-live" aria-label="VayuLok conditions">
      <VayuLokUiStyles />
      {/* Search is ALWAYS rendered - it does not wait for the map to paint, so a user can look up
          a city or pincode while the map is still loading or if it fails entirely. The map is a
          visualization layer, not a prerequisite for searching or for the environmental data. */}
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
              aria-activedescendant={ open && active >= 0 ? `vl-live-search-option-${active}` : undefined }
              aria-autocomplete="list"
              autoComplete="off"
              autoCorrect="off"
              spellCheck={ false }
              placeholder="Search a city or pincode"
              value={ query }
              onChange={ onQueryChange }
              onFocus={ () => {
                if ( query.trim() ) {
                  if ( results.length ) setOpen( true );
                  else void runSearch( query );
                }
              } }
              onKeyDown={ onKeyDown }
            />
            <VoiceSearchMic
              onTranscript={ transcript => {
                if ( searchTimer.current ) clearTimeout( searchTimer.current );
                autocompleteTokenRef.current = null;
                setQuery( transcript );
                void runSearch( transcript );
              } }
            />
          </div>
          <ul className="vl-live-search-results" id="vl-live-search-results" role="listbox" aria-label="Matching places" hidden={ !open || !results.length }>
            { results.map( ( r, i ) => (
              <li key={ `${r.name}-${r.addr}-${i}` } id={ `vl-live-search-option-${i}` } role="option" aria-selected={ i === active } onPointerDown={ e => { e.preventDefault(); void choose( r ); } }>
                <svg className="vl-live-search-result-icon" viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.location } /></svg>
                <span className="vl-live-search-result-text">
                  <strong>{ r.name }</strong>{ r.addr && <span>{ r.addr }</span> }
                </span>
              </li>
            ) ) }
          </ul>
          {/* "Searching…" is announced to screen readers (aria-live) but visually hidden, so the
              field stays light and uncluttered while typing. Only genuine end states - no result,
              or an actual failure - show visible helper text. */}
          { searchStatus === 'searching' && <p className="vl-live-sr-only" role="status" aria-live="polite">Searching places…</p> }
          { searchStatus === 'no-results' && <p className="vl-live-search-status" role="status">Place not found.</p> }
          { searchStatus === 'unavailable' && <p className="vl-live-search-status" role="status">Search unavailable.</p> }
        </div>
      </div>

      <div className="vl-live-shell">


        <div className="vl-live-workspace">
          <section className="vl-live-map-region" aria-label="Map">
            <div className="vl-live-map-shell">

              { detailTab === 'weather' && weatherVisual && mapVisible && (
                <div
                  className={ `vl-live-weather-visual ${weatherVisual.className}` }
                  style={ {
                    '--vl-sky-opacity': weatherVisual.skyOpacity,
                    '--vl-cloud-opacity': weatherVisual.cloudOpacity,
                  } as React.CSSProperties }
                  aria-hidden="true"
                >
                  <div className="vl-live-sky-wash" />
                  <div className="vl-live-cloud-field"><i /><i /><i /><i /></div>
                </div>
              ) }

              {/* FLOATING AIR QUALITY CARD. Overlays the map in the top-left corner, inset so
                  it never reaches Google's bottom-left logo or bottom-right legal notices. The
                  markup stays INLINE here (styled-jsx scopes only statically-visible elements),
                  every class is vl-live- prefixed, and it renders live Air content only when
                  `air` is present - on the keyless path (air === null) only the static shell
                  (header + toggle + honest empty state) shows, firing no fetch of its own. */}
              <div className="vl-live-mobile-snapshot" aria-label="Current VayuLok summary">
                <div className="vl-live-mobile-snapshot-head" data-wc-no-translate="true">
                  <span>
                    <strong>{ place.name }</strong>
                    <small suppressHydrationWarning>{ clockNow == null
                      ? 'Local time'
                      : locationTime.source === 'pending'
                        ? 'Resolving local time…'
                        : locationTime.source === 'unavailable'
                          ? 'Local time unavailable'
                          : `${locationClock} · ${locationZoneLabel}` }</small>
                  </span>
                  <div
                    className={ `vl-live-mobile-mode ${ detailTab === 'weather' ? 'is-weather' : 'is-air' }` }
                    role="group"
                    aria-label="VayuLok view"
                  >
                    <span className="vl-live-mobile-mode-indicator" aria-hidden="true" />
                    <button
                      type="button"
                      className="is-air"
                      aria-label="Air quality"
                      aria-pressed={ detailTab === 'air' }
                      title="Air quality"
                      onClick={ () => { setDetailTab( 'air' ); onModeChange?.( 'air' ); } }
                    >
                      <svg className="vl-live-mode-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <path d="M4 8h10.5a2.5 2.5 0 1 0-2.1-3.85" />
                        <path d="M4 12h14a2 2 0 1 1-1.7 3.05" />
                        <path d="M4 16h7.5a2 2 0 1 1-1.7 3.05" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      className="is-weather"
                      aria-label="Weather"
                      aria-pressed={ detailTab === 'weather' }
                      title="Weather"
                      onClick={ () => { setDetailTab( 'weather' ); onModeChange?.( 'weather' ); } }
                    >
                      <svg className="vl-live-mode-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <circle cx="8" cy="8" r="3" />
                        <path d="M8 2V1M8 15v-1M2 8H1M15 8h-1M3.8 3.8 3 3M13 13l-.8-.8M12.2 3.8 13 3" />
                        <path d="M9.5 19h8a3.5 3.5 0 0 0 .3-6.99A5 5 0 0 0 8.6 13.5 2.75 2.75 0 0 0 9.5 19Z" />
                      </svg>
                    </button>
                  </div>
                </div>

                { detailTab === 'air' ? (
                  air ? (
                    <div className="vl-live-mobile-snapshot-body is-air">
                      <div className="vl-live-mobile-primary">
                        <strong data-wc-no-translate="true">{ air.aqiDisplay || Math.round( air.aqi ) }</strong>
                        <span>{ aqiScaleLabel }</span>
                      </div>
                      <div className="vl-live-mobile-copy">
                        <strong>{ airQualityCategoryLabel( air.word ) }</strong>
                        { air.dominant && <span><b>Dominant</b> { dominantPollutantLabel( air.dominant, air.pollutants ) }</span> }
                        { air.pollutants.slice( 0, 2 ).map( pollutant => (
                          <span key={ `mobile-${pollutant.code}` }>
                            <b>{ pollutant.label }</b>{' '}
                            <span data-wc-no-translate="true">{ formatPollutantValue( pollutant.value ) } { pollutant.unit }</span>
                          </span>
                        ) ) }
                        { airAge && (
                          <VayuLokFreshnessStamp className={ airAge.stale ? 'vl-live-freshness is-stale' : 'vl-live-freshness' } aria-label={ airAge.label } iconPath={ MATERIAL_SYMBOL_PATHS.schedule } iconClassName="vl-live-freshness-icon" text={ freshnessTimeLabel( airAge.label ) } />
                        ) }
                      </div>
                    </div>
                  ) : dataLoading ? (
                    <p className="vl-live-mobile-empty" role="status" aria-live="polite">Loading air quality…</p>
                  ) : null
                ) : weather ? (
                  <div className="vl-live-mobile-snapshot-body is-weather">
                    <div className="vl-live-mobile-primary">
                      <strong data-wc-no-translate="true">{ Number.isFinite( weather.temp ) ? `${weather.temp}°` : '—' }</strong>
                      <span>{ weather.condition || 'Weather' }</span>
                    </div>
                    <div className="vl-live-mobile-copy">
                      { Number.isFinite( weather.feelsLike ) && <span><b>Feels</b> <span data-wc-no-translate="true">{ weather.feelsLike }°</span></span> }
                      { Number.isFinite( weather.humidity ) && <span><b>Humidity</b> <span data-wc-no-translate="true">{ weather.humidity }%</span></span> }
                      { Number.isFinite( weather.windSpeed ) && <span><b>Wind</b> <span data-wc-no-translate="true">{ weather.windSpeed } { weather.windUnit || 'km/h' }</span></span> }
                    </div>
                  </div>
                ) : dataLoading ? (
                  <p className="vl-live-mobile-empty" role="status" aria-live="polite">Loading weather…</p>
                ) : null }
              </div>

              <div className="vl-live-air-card-wrap">
              <aside className="vl-live-air-card" aria-label="Air quality details">
                {/* Place name (as Google returned it), the live clock and the zone label are raw
                    data, not UI copy - kept out of translation per the data-honesty rule. */}
                <div className="vl-live-air-context" aria-label="Selected location and local time" data-wc-no-translate="true">
                  <span className="vl-live-air-context-item is-location" title={ place.addr || place.name }>
                    <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.location } /></svg>
                    <strong>{ place.name }</strong>
                  </span>
                  <span
                    className="vl-live-air-context-item is-time"
                    title={ locationTime.source === 'google'
                      ? `${locationTime.timeZoneName} from Google Time Zone API`
                      : locationTime.source === 'default'
                        ? 'India Standard Time'
                        : locationTime.source === 'pending'
                          ? 'Resolving the selected place local time'
                          : 'Local time unavailable' }
                  >
                    <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.schedule } /></svg>
                    <span className="vl-live-local-datetime">
                      { clockNow == null ? (
                        <small className="vl-live-local-time-status">Local time</small>
                      ) : locationTimeReady ? (
                        <time dateTime={ new Date( clockNow ).toISOString() } suppressHydrationWarning>
                          { locationClock } · { locationZoneLabel }
                        </time>
                      ) : (
                        <small className="vl-live-local-time-status">{ locationTime.source === 'pending' ? 'Resolving local time…' : 'Local time unavailable' }</small>
                      ) }
                    </span>
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
                    // Only the active tab's panel is rendered, so only it may point at one -
                    // an aria-controls naming an absent id is a dangling reference.
                    aria-controls={ detailTab === 'air' ? 'vl-live-air-panel' : undefined }
                    aria-selected={ detailTab === 'air' }
                    className={ `vl-live-air-toggle-btn is-air ${detailTab === 'air' ? 'is-active' : ''}`.trim() }
                    onClick={ () => { setDetailTab( 'air' ); onModeChange?.( 'air' ); } }
                  >
                    <i className="vl-live-air-toggle-dot" aria-hidden="true" />Air
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="vl-live-weather-tab"
                    aria-controls={ detailTab === 'weather' ? 'vl-live-weather-panel' : undefined }
                    aria-selected={ detailTab === 'weather' }
                    className={ `vl-live-air-toggle-btn is-weather ${detailTab === 'weather' ? 'is-active' : ''}`.trim() }
                    onClick={ () => { setDetailTab( 'weather' ); onModeChange?.( 'weather' ); } }
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
                          <span className="vl-live-air-aqi-unit" aria-hidden="true">{ aqiScaleLabel }</span>
                        </div>
                        <div className="vl-live-air-gauge-meta">
                          <strong className="vl-live-air-gauge-word">{ airQualityCategoryLabel( air.word ) }</strong>
                          <div className="vl-live-air-summary-meta">
                            <span className="vl-live-air-summary-chip">
                              <svg className="vl-live-air-summary-icon" viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.air } /></svg>
                              <strong>{ aqiScaleLabel }</strong> { air.aqiDisplay || Math.round( air.aqi ) }
                            </span>
                            { air.dominant && (
                              <span className="vl-live-air-summary-chip">
                                <svg className="vl-live-air-summary-icon" viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.eco } /></svg>
                                <strong>Dominant</strong> { dominantPollutantLabel( air.dominant, air.pollutants ) }
                              </span>
                            ) }
                            { airAge && (
                              <VayuLokFreshnessStamp className={ airAge.stale ? 'vl-live-data-age vl-live-freshness is-stale' : 'vl-live-data-age vl-live-freshness' } aria-label={ airAge.label } iconPath={ MATERIAL_SYMBOL_PATHS.schedule } iconClassName="vl-live-freshness-icon" text={ freshnessTimeLabel( airAge.label ) } />
                            ) }
                          </div>
                        </div>
                      </div>

                      { air.pollutants.length > 0 && (
                        <div className="vl-live-air-pollutants">
                          <h2 className="vl-live-air-pollutants-title">Pollutants</h2>
                          <ul className="vl-live-air-pollutant-list">
                            { air.pollutants.map( p => (
                              <li className="vl-live-air-pollutant-row" key={ p.code }>
                                <span className="vl-live-air-pollutant-label">{ p.label }</span>
                                <span className="vl-live-air-pollutant-value" data-wc-no-translate="true">{ formatPollutantValue( p.value ) } <small title={ unitTermLabel( p.unit ) }>{ p.unit }</small></span>
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

                      {/* SECTION 1 - HEATMAP. This control keeps the
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
                          <h2 className="vl-live-air-forecast-title">Air Forecast</h2>
                          <div className="vl-live-air-forecast-head-actions">
                            <div className="vl-live-air-range" role="group" aria-label="Air forecast range">
                              { ( [ 24, 48, 96 ] as const ).map( hours => (
                                <VayuLokCompactPill key={ hours } className={ airForecastHours === hours ? 'is-active' : '' } aria-pressed={ airForecastHours === hours } onClick={ () => setAirForecastHours( hours ) }>
                                  { hours }h
                                </VayuLokCompactPill>
                              ) ) }
                            </div>
                            { airForecast.length > 0 && (
                              <div className="vl-live-air-scroll-nav" role="group" aria-label="Scroll hourly forecast">
                                <button
                                  type="button"
                                  className="vl-live-air-scroll-btn"
                                  aria-label="Previous forecast hours"
                                  onClick={ () => airForecastStripRef.current?.scrollBy( { left: -240, behavior: 'smooth' } ) }
                                >
                                  <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.chevronLeft } /></svg>
                                </button>
                                <button
                                  type="button"
                                  className="vl-live-air-scroll-btn"
                                  aria-label="Next forecast hours"
                                  onClick={ () => airForecastStripRef.current?.scrollBy( { left: 240, behavior: 'smooth' } ) }
                                >
                                  <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.chevronRight } /></svg>
                                </button>
                              </div>
                            ) }
                          </div>
                        </div>
                        { airForecastStatus === 'loading' && !airForecast.length ? (
                          // LOADING: light skeleton cards while forecast:lookup is in flight.
                          <div className="vl-live-air-forecast-strip is-skeleton" aria-hidden="true">
                            { Array.from( { length: 6 } ).map( ( _, i ) => (
                              <span key={ i } className="vl-live-air-forecast-card is-skeleton" />
                            ) ) }
                          </div>
                        ) : airForecastStatus === 'error' ? (
                          // ERROR: concise user-facing fallback; technical detail is logged in dev.
                          <p className="vl-live-air-history-empty" role="status">Air forecast unavailable.</p>
                        ) : airForecastStatus === 'empty' ? (
                          // EMPTY: a valid Google response with no usable forecast rows.
                          <p className="vl-live-air-history-empty" role="status">No air forecast for this place.</p>
                        ) : airForecast.length ? (
                          <>
                            <VayuLokHorizontalRail ref={ airForecastStripRef } className="vl-live-air-forecast-strip" aria-label={ `Next ${airForecastHours} hours air forecast` }>
                              { airForecast.slice( 0, airForecastHours ).map( ( point, idx ) => (
                                <VayuLokDataCard key={ point.time } className={ `vl-live-air-forecast-card ${airForecastInspectIdx === idx ? 'is-active' : ''}`.trim() } aria-pressed={ airForecastInspectIdx === idx } onFocus={ e => e.currentTarget.scrollIntoView?.( { block: 'nearest', inline: 'nearest' } ) } onClick={ e => { setAirForecastInspectIdx( idx ); e.currentTarget.scrollIntoView?.( { block: 'nearest', inline: 'nearest' } ); } }>
                                  <span>{ formatHistoryPointLabel( point.time, displayTimeZoneId, locationZoneLabel ) }</span>
                                  <strong>AQI <span data-wc-no-translate="true">{ point.aqi }</span></strong>
                                  { point.word && <small>{ point.word }</small> }
                                  { Number.isFinite( point.pm25 ) && <small>PM2.5 <span data-wc-no-translate="true">{ Math.round( point.pm25 as number ) } µg/m³</span></small> }
                                  { point.pollutants?.find( p => p.code === 'pm10' ) && <small>PM10 <span data-wc-no-translate="true">{ formatPollutantValue( point.pollutants.find( p => p.code === 'pm10' )!.value ) } { point.pollutants.find( p => p.code === 'pm10' )!.unit }</span></small> }
                                </VayuLokDataCard>
                              ) ) }
                            </VayuLokHorizontalRail>
                            { airForecast[ airForecastInspectIdx ] && (
                              <div className="vl-live-air-forecast-detail">
                                { airForecast[ airForecastInspectIdx ].dominant && (
                                  <span><strong>Dominant</strong> { POLLUTANT_LABELS[ airForecast[ airForecastInspectIdx ].dominant as string ] || airForecast[ airForecastInspectIdx ].dominant }</span>
                                ) }
                                { airForecast[ airForecastInspectIdx ].localAqi != null && airForecast[ airForecastInspectIdx ].universalAqi != null && (
                                  <span><strong>Local / Universal</strong> { airForecast[ airForecastInspectIdx ].localAqi } / { airForecast[ airForecastInspectIdx ].universalAqi }</span>
                                ) }
                                { airForecast[ airForecastInspectIdx ].pollutants?.map( p => (
                                  <span key={ p.code }>
                                    <strong>{ p.label || POLLUTANT_LABELS[ p.code ] || p.code }</strong>{' '}
                                    <span data-wc-no-translate="true">{ formatPollutantValue( p.value ) } { p.unit }</span>
                                  </span>
                                ) ) }
                                { ( () => {
                                  const point = airForecast[ airForecastInspectIdx ];
                                  const dominant = point.pollutants?.find( p => p.code === point.dominant );
                                  if ( !dominant ) return null;
                                  return (
                                    <>
                                      { dominant.sources && <span><strong>Sources</strong> { shortAirInfo( dominant.sources ) }</span> }
                                      { dominant.effects && <span><strong>Effects</strong> { shortAirInfo( dominant.effects ) }</span> }
                                    </>
                                  );
                                } )() }
                              </div>
                            ) }
                          </>
                        ) : (
                          <p className="vl-live-air-history-empty">Air forecast appears here once a place is selected.</p>
                        ) }
                      </div>

                      {/* SECTION 2 - HEALTH RECOMMENDATIONS. Only Google's returned
                          population-specific text is rendered. Missing groups disappear rather than
                          receiving static/fabricated advice. */}
                      { activeHealthPersona && (
                        <div className="vl-live-air-health">
                          <div className="vl-live-air-health-head">
                            <h2 className="vl-live-air-health-title">Health Recommendations</h2>
                            <div className="vl-live-air-health-head-nav" role="group" aria-label="Health recommendations pagination">
                              <button
                                type="button"
                                className="vl-live-air-health-page"
                                aria-label="Previous health profile"
                                disabled={ healthPersona <= 0 }
                                onClick={ () => setHealthPersona( current => Math.max( 0, current - 1 ) ) }
                              >
                                <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.chevronLeft } /></svg>
                              </button>
                              <button
                                type="button"
                                className="vl-live-air-health-page"
                                aria-label="Next health profile"
                                disabled={ healthPersona >= liveHealthPersonas.length - 1 }
                                onClick={ () => setHealthPersona( current => Math.min( liveHealthPersonas.length - 1, current + 1 ) ) }
                              >
                                <svg viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.chevronRight } /></svg>
                              </button>
                            </div>
                          </div>
                          <div className="vl-live-air-health-rail-shell">
                            <VayuLokHorizontalRail ref={ healthRailRef } className="vl-live-air-health-tabs" role="tablist" aria-label="Health recommendation profiles">
                            { liveHealthPersonas.map( ( persona, idx ) => (
                              <VayuLokIconAction
                                key={ persona.id }
                                role="tab"
                                id={ `vl-live-air-health-tab-${persona.id}` }
                                aria-controls="vl-live-air-health-panel"
                                aria-selected={ healthPersona === idx }
                                aria-label={ persona.label }
                                title={ persona.label }
                                className={ `vl-live-air-health-tab ${healthPersona === idx ? 'is-active' : ''}`.trim() }
                                onFocus={ e => e.currentTarget.scrollIntoView?.( { block: 'nearest', inline: 'nearest' } ) }
                                onClick={ e => { setHealthPersona( idx ); e.currentTarget.scrollIntoView?.( { block: 'nearest', inline: 'nearest' } ); } }
                              >
                                <span className="vl-live-air-health-icon-wrap" aria-hidden="true">
                                  <svg viewBox="0 -960 960 960" className="vl-live-air-health-icon">
                                    <path d={ MATERIAL_SYMBOL_PATHS[ persona.icon ] } />
                                  </svg>
                                </span>
                                <span className="vl-live-air-health-tooltip" aria-hidden="true">{ persona.label }</span>
                              </VayuLokIconAction>
                            ) ) }
                            </VayuLokHorizontalRail>
                          </div>
                          <div
                            className="vl-live-air-health-panel"
                            role="tabpanel"
                            id="vl-live-air-health-panel"
                            aria-labelledby={ `vl-live-air-health-tab-${activeHealthPersona.id}` }
                          >
                            <strong className="vl-live-air-health-persona">{ activeHealthPersona.label }</strong>
                            <p className="vl-live-air-health-text">{ activeHealthPersona.recommendation }</p>
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
                                  <h2 className="vl-live-air-history-title">Hourly History</h2>
                                  <div className="vl-live-air-range" role="group" aria-label="Air history range">
                                    { ( [ 24, 168 ] as const ).map( hours => (
                                      <VayuLokCompactPill key={ hours } className={ historyRange === hours ? 'is-active' : '' } aria-pressed={ historyRange === hours } onClick={ () => setHistoryRange( hours ) }>
                                        { hours === 24 ? '24h' : '7d' }
                                      </VayuLokCompactPill>
                                    ) ) }
                                  </div>
                                </div>
                              </>
                            );
                          }
                          const points = airHistory;
                          const currentIdx = Math.max( 0, points.length - 1 );
                          const current = points[ currentIdx ];
                          const latest = points[ points.length - 1 ];

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
                          const stampPoint = inspected || current;
                          const stamp = formatHistoryStamp( stampPoint.time, displayTimeZoneId, locationZoneLabel );
                          const inspectX = inspectedIdx == null ? 0 : xAt( inspectedIdx );
                          const inspectY = inspected ? yAt( inspected.aqi ) : 0;
                          const inspectPoint = ( clientX: number, target: HTMLElement ) => {
                            const rect = target.getBoundingClientRect();
                            const ratio = rect.width > 0 ? clamp( ( clientX - rect.left ) / rect.width, 0, 1 ) : 0;
                            setHistoryInspectIdx( Math.round( ratio * ( points.length - 1 ) ) );
                          };

                          // Weekday gridlines follow the selected destination's local timezone,
                          // matching the timestamp above instead of mixing local context with UTC.
                          const dayLabel = new Intl.DateTimeFormat( 'en-US', { timeZone: displayTimeZoneId, weekday: 'short' } );
                          const dayKey = new Intl.DateTimeFormat( 'en-CA', { timeZone: displayTimeZoneId, year: 'numeric', month: '2-digit', day: '2-digit' } );
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
                                <h2 className="vl-live-air-history-title">Hourly History</h2>
                                <div className="vl-live-air-history-head-meta">
                                  <div className="vl-live-air-range" role="group" aria-label="Air history range">
                                    { ( [ 24, 168 ] as const ).map( hours => (
                                      <VayuLokCompactPill key={ hours } className={ historyRange === hours ? 'is-active' : '' } aria-pressed={ historyRange === hours } onClick={ () => setHistoryRange( hours ) }>
                                        { hours === 24 ? '24h' : '7d' }
                                      </VayuLokCompactPill>
                                    ) ) }
                                  </div>


                                </div>
                              </div>
                              <div
                                className={ `vl-live-air-history-chart vl-live-air-sev-${aqiCategory( current.aqi ).sev}` }
                                /* Keyboard-accessible as a slider over the history points: Tab to
                                   focus, Left/Right (or Up/Down) to step through hours, Home/End to
                                   jump to the oldest/newest. The visible tooltip and the sr-only
                                   live region below announce the inspected hour's time and AQI. */
                                role="slider"
                                tabIndex={ 0 }
                                aria-label={ `AQI history, ${historyRangeLabel( historyRange )}. Use arrow keys to inspect an hour.` }
                                aria-valuemin={ 0 }
                                aria-valuemax={ points.length - 1 }
                                aria-valuenow={ inspectedIdx == null ? currentIdx : inspectedIdx }
                                aria-valuetext={ inspected
                                  ? `${formatHistoryPointLabel( inspected.time, displayTimeZoneId, locationZoneLabel )}, AQI ${Math.round( inspected.aqi )}`
                                  : `Current, AQI ${Math.round( current.aqi )}` }
                                onPointerMove={ e => {
                                  if ( e.pointerType === 'mouse' || e.pointerType === 'pen' ) inspectPoint( e.clientX, e.currentTarget );
                                } }
                                onPointerDown={ e => inspectPoint( e.clientX, e.currentTarget ) }
                                onKeyDown={ e => {
                                  const last = points.length - 1;
                                  const base = inspectedIdx == null ? currentIdx : inspectedIdx;
                                  if ( e.key === 'ArrowLeft' || e.key === 'ArrowDown' ) {
                                    e.preventDefault(); setHistoryInspectIdx( Math.max( 0, base - 1 ) );
                                  } else if ( e.key === 'ArrowRight' || e.key === 'ArrowUp' ) {
                                    e.preventDefault(); setHistoryInspectIdx( Math.min( last, base + 1 ) );
                                  } else if ( e.key === 'Home' ) {
                                    e.preventDefault(); setHistoryInspectIdx( 0 );
                                  } else if ( e.key === 'End' ) {
                                    e.preventDefault(); setHistoryInspectIdx( last );
                                  } else if ( e.key === 'Escape' ) {
                                    setHistoryInspectIdx( null );
                                  }
                                } }
                              >
                                <svg viewBox={ `0 0 ${W} ${H}` } className="vl-live-air-history-svg" preserveAspectRatio="none">
                                  { ticks.map( ( t, i ) => (
                                    <g key={ `${t.label}-${i}` }>
                                      <line className="vl-live-air-history-grid" x1={ t.x } y1={ padTop } x2={ t.x } y2={ H - padBottom } />
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
                                {/* Screen-reader announcement of the inspected hour and AQI.
                                    The visual floating tooltip is intentionally omitted. */}
                                <span className="vl-live-sr-only" role="status" aria-live="polite">
                                  { inspected
                                    ? `${formatHistoryPointLabel( inspected.time, displayTimeZoneId, locationZoneLabel )}, AQI ${Math.round( inspected.aqi )}`
                                    : '' }
                                </span>
                              </div>
                              { inspected && (
                                <div className="vl-live-air-forecast-detail vl-live-air-history-detail">
                                  <span><strong>AQI</strong> <span data-wc-no-translate="true">{ inspected.aqi }</span></span>
                                  { inspected.dominant && <span><strong>Dominant</strong> { POLLUTANT_LABELS[ inspected.dominant ] || inspected.dominant }</span> }
                                  { inspected.localAqi != null && inspected.universalAqi != null && (
                                    <span><strong>Local / Universal</strong> <span data-wc-no-translate="true">{ inspected.localAqi } / { inspected.universalAqi }</span></span>
                                  ) }
                                  { inspected.pollutants?.map( p => (
                                    <span key={ p.code } className="vl-live-air-history-pollutant">
                                      <strong>{ p.label || POLLUTANT_LABELS[ p.code ] || p.code }</strong>{' '}
                                      <span data-wc-no-translate="true">{ formatPollutantValue( p.value ) } { p.unit }</span>

                                    </span>
                                  ) ) }
                                </div>
                              ) }
                              <div className="vl-live-air-history-stamp" aria-label="Reading time">
                                <svg className="vl-live-air-history-stamp-icon" viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.schedule } /></svg>
                                <span data-wc-no-translate="true">{ stamp }</span>
                              </div>
                              <span className="vl-live-sr-only">Latest reading { Math.round( latest.aqi ) }, { latest.word }.</span>
                            </>
                          );
                        } )() }
                      </div>
                    </div>
                  ) : (
                    <div className="vl-live-air-panel" role="tabpanel" id="vl-live-air-panel" aria-labelledby="vl-live-air-tab" aria-label="Air details">
                      <p className="vl-live-air-empty" role="status">{ dataLoading ? 'Loading air quality…' : hasSelection ? 'Air quality unavailable.' : 'Choose a place for air quality.' }</p>
                    </div>
                  )
                ) }

                { detailTab === 'weather' && (
                  <div className="vl-live-air-panel" role="tabpanel" id="vl-live-weather-panel" aria-labelledby="vl-live-weather-tab" aria-label="Weather details">
                    { weather ? (
                      <>
                        {/* CURRENT CONDITIONS - large primary block, mirroring the Air AQI hero. */}
                        <div className="vl-live-wx-now">
                          <div className="vl-live-wx-now-head">
                            { weather.icon && <img className="vl-live-wx-now-icon" src={ `${weather.icon}.png` } alt="" data-wc-no-translate="true" aria-hidden="true" /> }
                            <div>
                              { Number.isFinite( weather.temp ) && <strong className="vl-live-wx-now-temp" data-wc-no-translate="true">{ weather.temp }°</strong> }
                              { weather.condition && <span className="vl-live-wx-now-cond">{ weather.condition }</span> }
                            </div>
                          </div>
                          <div className="vl-live-wx-now-sub">
                            { Number.isFinite( weather.feelsLike ) && <span>Feels <span data-wc-no-translate="true">{ weather.feelsLike }°</span></span> }
                            { Number.isFinite( weather.temperatureChange ) && weather.temperatureChange !== 0 && (
                              <span data-wc-no-translate="true">{ ( weather.temperatureChange as number ) > 0 ? '↑' : '↓' } { Math.abs( weather.temperatureChange as number ) }° / 24h</span>
                            ) }
                          </div>
                        </div>
                        { weatherAge && (
                          <div className={ `vl-live-wx-freshness vl-live-freshness ${weatherAge.stale ? 'is-stale' : ''}`.trim() } aria-label={ weatherAge.label }>
                            <svg className="vl-live-freshness-icon" viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.schedule } /></svg>
                            <span>{ freshnessTimeLabel( weatherAge.label ) }</span>
                          </div>
                        ) }

                        {/* CURRENT METRICS - compact grid, only fields Google returned. */}
                        <ul className="vl-live-wx-grid">
                          { ( [
                            Number.isFinite( weather.dayMin ) && Number.isFinite( weather.dayMax ) ? { k: 'Day range', v: `${weather.dayMin}° — ${weather.dayMax}°` } : null,
                            Number.isFinite( weather.humidity ) ? { k: 'Humidity', v: `${weather.humidity}%` } : null,
                            Number.isFinite( weather.rainProb ) ? { k: 'Rain', v: `${weather.rainProb}%${Number.isFinite( weather.rainMm ) ? ` · ${weather.rainMm} mm` : ''}` } : null,
                            Number.isFinite( weather.windSpeed ) ? { k: 'Wind', v: `${weather.windSpeed} ${weather.windUnit || 'km/h'}${weather.windDir ? ` ${weather.windDir}` : ''}${Number.isFinite( weather.windDeg ) ? ` · ${Math.round( weather.windDeg as number )}°` : ''}` } : null,
                            Number.isFinite( weather.windGust ) ? { k: 'Gust', v: `${weather.windGust} ${weather.windUnit || 'km/h'}` } : null,
                            Number.isFinite( weather.uv ) ? { k: 'UV', v: `${weather.uv}` } : null,
                            Number.isFinite( weather.visibilityKm ) ? { k: 'Visibility', v: `${weather.visibilityKm} km` } : null,
                            Number.isFinite( weather.pressureHpa ) ? { k: 'Pressure', v: `${weather.pressureHpa} mb` } : null,
                            Number.isFinite( weather.cloudCover ) ? { k: 'Cloud', v: `${weather.cloudCover}%` } : null,
                            Number.isFinite( weather.dewPoint ) ? { k: 'Dew point', v: `${weather.dewPoint}°` } : null,
                            Number.isFinite( weather.heatIndex ) ? { k: 'Heat index', v: `${weather.heatIndex}°` } : null,
                            Number.isFinite( weather.wetBulb ) ? { k: 'Wet bulb', v: `${weather.wetBulb}°` } : null,
                            Number.isFinite( weather.windChill ) ? { k: 'Wind chill', v: `${weather.windChill}°` } : null,
                            weather.precipitationType ? { k: 'Precipitation', v: weather.precipitationType.replace( /_/g, ' ' ) } : null,
                            Number.isFinite( weather.recentQpf ) ? { k: '24h precip', v: `${weather.recentQpf} mm` } : null,
                            Number.isFinite( weather.stormProb ) && ( weather.stormProb as number ) > 0 ? { k: 'Storm', v: `${weather.stormProb}%` } : null,
                          ] as ( { k: string; v: string } | null )[] ).filter( Boolean ).map( item => (
                            <li key={ ( item as { k: string } ).k } className="vl-live-wx-grid-item">
                              <span className="vl-live-wx-grid-k">{ ( item as { k: string } ).k }</span>
                              <span className="vl-live-wx-grid-v" data-wc-no-translate="true">{ ( item as { v: string } ).v }</span>
                            </li>
                          ) ) }
                        </ul>

                        {/* ALERTS - empty/unsupported states stay out of the layout. A provider
                            failure remains visible, matching VayuLok's failure contract; real
                            alerts render with their authority/source attribution as before. */}
                        { ( weatherAlertStatus === 'error' || ( weatherAlertStatus === 'active' && weatherAlerts.length > 0 ) ) && (
                          <div className="vl-live-wx-alerts">
                            <h2 className="vl-live-air-forecast-title">Alerts</h2>
                            { weatherAlertStatus === 'error' ? (
                              <p className="vl-live-air-history-empty" role="status">Alerts unavailable.</p>
                            ) : weatherAlerts.map( alert => (
                              <div key={ alert.id } className={ `vl-live-wx-alert sev-${( alert.severity || 'minor' ).toLowerCase()}` }>
                              <strong>{ alert.title }</strong>
                              { alert.eventType && <span className="vl-live-wx-alert-event">{ alert.eventType.replace( /_/g, ' ' ) }</span> }
                              { ( alert.severity || alert.certainty || alert.urgency ) && (
                                <span className="vl-live-wx-alert-meta" data-wc-no-translate="true">
                                  { [ alert.severity, alert.certainty, alert.urgency ].filter( Boolean ).join( ' · ' ) }
                                </span>
                              ) }
                              { alert.area && <span className="vl-live-wx-alert-area">{ alert.area }</span> }
                              { ( alert.startTime || alert.expires ) && (
                                <span className="vl-live-wx-alert-time" data-wc-no-translate="true">
                                  { alert.startTime ? `Starts ${formatHistoryPointLabel( new Date( alert.startTime ).getTime(), displayTimeZoneId, locationZoneLabel )}` : '' }
                                  { alert.startTime && alert.expires ? ' · ' : '' }
                                  { alert.expires ? `Ends ${formatHistoryPointLabel( new Date( alert.expires ).getTime(), displayTimeZoneId, locationZoneLabel )}` : '' }
                                </span>
                              ) }
                              { alert.description && <p>{ alert.description }</p> }
                              { alert.instruction?.map( ( item, idx ) => <p key={ `instruction-${idx}` }><strong>Instruction</strong> { item }</p> ) }
                              { alert.safetyRecommendations?.map( ( item, idx ) => (
                                <p key={ `safety-${idx}` }><strong>Safety</strong> { item.directive }{ item.subtext ? ` ${item.subtext}` : '' }</p>
                              ) ) }
                              { alert.polygon && (
                                <button
                                  type="button"
                                  className="vl-live-wx-alert-map-btn"
                                  aria-pressed={ activeAlertBoundaryId === alert.id }
                                  onClick={ () => activeAlertBoundaryId === alert.id ? clearAlertBoundary() : showAlertBoundary( alert ) }
                                >
                                  { activeAlertBoundaryId === alert.id ? 'Clear affected area' : 'View affected area' }
                                </button>
                              ) }
                              { alert.source && (
                                <small className="vl-live-wx-alert-src">
                                  Source:{' '}
                                  { alert.sourceUrl ? (
                                    <a href={ alert.sourceUrl } target="_blank" rel="noreferrer" data-wc-no-translate="true">{ alert.source }</a>
                                  ) : <span data-wc-no-translate="true">{ alert.source }</span> }
                                  { alert.sourcePublisher && alert.sourcePublisher !== alert.source ? <span data-wc-no-translate="true"> · { alert.sourcePublisher }</span> : null }
                                </small>
                              ) }
                            </div>
                            ) ) }
                          </div>
                        ) }

                        {/* HOURLY FORECAST - reuses the Air Forecast strip interaction. */}
                        { weatherHourly.length > 0 && (
                          <div className="vl-live-air-forecast">
                            <div className="vl-live-air-forecast-head">
                              <h2 className="vl-live-air-forecast-title">Hourly Forecast</h2>
                              <div className="vl-live-air-range" role="group" aria-label="Weather forecast range">
                                { ( [ 24, 48, 96 ] as const ).map( hours => (
                                  <VayuLokCompactPill key={ hours } className={ weatherHours === hours ? 'is-active' : '' } aria-pressed={ weatherHours === hours } onClick={ () => setWeatherHours( hours ) }>
                                    { hours }h
                                  </VayuLokCompactPill>
                                ) ) }
                              </div>
                            </div>
                            <VayuLokHorizontalRail className="vl-live-air-forecast-strip" aria-label={ `Next ${weatherHours} hours weather forecast` }>
                              { weatherHourly.slice( 0, weatherHours ).map( ( hour, idx ) => (
                                <VayuLokDataCard key={ hour.time } className={ `vl-live-air-forecast-card ${weatherHourInspectIdx === idx ? 'is-active' : ''}`.trim() } aria-pressed={ weatherHourInspectIdx === idx } onFocus={ e => e.currentTarget.scrollIntoView?.( { block: 'nearest', inline: 'nearest' } ) } onClick={ e => { setWeatherHourInspectIdx( idx ); e.currentTarget.scrollIntoView?.( { block: 'nearest', inline: 'nearest' } ); } }>
                                  <span>{ idx === 0 ? 'Now' : formatHistoryPointLabel( hour.time, displayTimeZoneId, locationZoneLabel ) }</span>
                                  { hour.icon && <img className="vl-live-wx-hour-icon" src={ `${hour.icon}.svg` } alt="" aria-hidden="true" /> }
                                  { Number.isFinite( hour.temp ) && <strong data-wc-no-translate="true">{ hour.temp }°</strong> }
                                  { hour.condition && <small>{ hour.condition }</small> }
                                  { Number.isFinite( hour.feelsLike ) && <small data-wc-no-translate="true">Feels { hour.feelsLike }°</small> }
                                  { Number.isFinite( hour.rainProb ) && <small data-wc-no-translate="true">Rain { hour.rainProb }%</small> }
                                  { Number.isFinite( hour.windSpeed ) && <small data-wc-no-translate="true">Wind { hour.windSpeed } { hour.windUnit || 'km/h' }{ hour.windDir ? ` ${hour.windDir}` : '' }</small> }
                                </VayuLokDataCard>
                              ) ) }
                            </VayuLokHorizontalRail>
                            { weatherHourInspectIdx != null && weatherHourly[ weatherHourInspectIdx ] && (
                              <div className="vl-live-air-forecast-detail">
                                { ( () => {
                                  const h = weatherHourly[ weatherHourInspectIdx ];
                                  const bits: { k: string; v: string }[] = [];
                                  if ( Number.isFinite( h.feelsLike ) ) bits.push( { k: 'Feels', v: `${h.feelsLike}°` } );
                                  if ( Number.isFinite( h.humidity ) ) bits.push( { k: 'Humidity', v: `${h.humidity}%` } );
                                  if ( Number.isFinite( h.rainMm ) ) bits.push( { k: 'Rain', v: `${h.rainMm} mm` } );
                                  if ( Number.isFinite( h.stormProb ) && ( h.stormProb as number ) > 0 ) bits.push( { k: 'Storm', v: `${h.stormProb}%` } );
                                  if ( Number.isFinite( h.windSpeed ) ) bits.push( { k: 'Wind', v: `${h.windSpeed} ${h.windUnit || 'km/h'}${h.windDir ? ` ${h.windDir}` : ''}${Number.isFinite( h.windDeg ) ? ` · ${Math.round( h.windDeg as number )}°` : ''}` } );
                                  if ( Number.isFinite( h.windGust ) ) bits.push( { k: 'Gust', v: `${h.windGust} ${h.windUnit || 'km/h'}` } );
                                  if ( Number.isFinite( h.uv ) ) bits.push( { k: 'UV', v: `${h.uv}` } );
                                  if ( Number.isFinite( h.visibilityKm ) ) bits.push( { k: 'Visibility', v: `${h.visibilityKm} km` } );
                                  if ( Number.isFinite( h.pressureHpa ) ) bits.push( { k: 'Pressure', v: `${h.pressureHpa} mb` } );
                                  if ( Number.isFinite( h.cloudCover ) ) bits.push( { k: 'Cloud', v: `${h.cloudCover}%` } );
                                  if ( Number.isFinite( h.dewPoint ) ) bits.push( { k: 'Dew point', v: `${h.dewPoint}°` } );
                                  if ( Number.isFinite( h.heatIndex ) ) bits.push( { k: 'Heat index', v: `${h.heatIndex}°` } );
                                  if ( Number.isFinite( h.wetBulb ) ) bits.push( { k: 'Wet bulb', v: `${h.wetBulb}°` } );
                                  if ( Number.isFinite( h.windChill ) ) bits.push( { k: 'Wind chill', v: `${h.windChill}°` } );
                                  if ( h.precipitationType ) bits.push( { k: 'Precipitation', v: h.precipitationType.replace( /_/g, ' ' ) } );
                                  if ( Number.isFinite( h.iceThicknessMm ) ) bits.push( { k: 'Ice', v: `${h.iceThicknessMm} mm` } );
                                  return bits.map( b => <span key={ b.k }><strong>{ b.k }</strong> <span data-wc-no-translate="true">{ b.v }</span></span> );
                                } )() }
                              </div>
                            ) }
                          </div>
                        ) }
                        { forecastFetchedAt && ( () => {
                          const age = relativeAgeLabel( forecastFetchedAt );
                          return (
                            <div className="vl-live-wx-freshness vl-live-freshness" aria-label={ `Forecast ${age.label.toLowerCase()}` }>
                              <svg className="vl-live-freshness-icon" viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.schedule } /></svg>
                              <span>{ freshnessTimeLabel( age.label ) }</span>
                            </div>
                          );
                        } )() }

                        {/* 10-DAY FORECAST - compact vertical rows, detail on selection. */}
                        { weatherDaily.length > 0 && (
                          <div className="vl-live-wx-daily">
                            <h2 className="vl-live-air-forecast-title">10-Day Forecast</h2>
                            <ul className="vl-live-wx-daily-list">
                              { weatherDaily.map( ( day, idx ) => (
                                <li key={ day.time }>
                                  <button type="button" className={ `vl-live-wx-daily-row ${weatherDayInspectIdx === idx ? 'is-active' : ''}`.trim() } aria-expanded={ weatherDayInspectIdx === idx } onClick={ () => { setWeatherDayPeriod( 'day' ); setWeatherDayInspectIdx( weatherDayInspectIdx === idx ? null : idx ); } }>
                                    <span className="vl-live-wx-daily-day">{ day.label }</span>
                                    { day.icon ? <img className="vl-live-wx-daily-icon" src={ `${day.icon}.png` } alt="" aria-hidden="true" data-wc-no-translate="true" /> : <span className="vl-live-wx-daily-icon-spacer" aria-hidden="true" /> }
                                    { day.condition && <span className="vl-live-wx-daily-cond">{ day.condition }</span> }
                                    <span className="vl-live-wx-daily-temp" data-wc-no-translate="true">{ Number.isFinite( day.min ) ? `${day.min}°` : '' }{ Number.isFinite( day.min ) && Number.isFinite( day.max ) ? ' — ' : '' }{ Number.isFinite( day.max ) ? `${day.max}°` : '' }</span>
                                    { Number.isFinite( day.rainProb ) && <span className="vl-live-wx-daily-rain" data-wc-no-translate="true">{ day.rainProb }%</span> }
                                  </button>
                                  { weatherDayInspectIdx === idx && (
                                    <div className="vl-live-wx-daily-expand">
                                      <div className="vl-live-air-range vl-live-wx-period-toggle" role="group" aria-label={ `${day.label} forecast period` }>
                                        <button type="button" className={ weatherDayPeriod === 'day' ? 'is-active' : '' } aria-pressed={ weatherDayPeriod === 'day' } onClick={ () => setWeatherDayPeriod( 'day' ) }>Day</button>
                                        <button type="button" className={ weatherDayPeriod === 'night' ? 'is-active' : '' } aria-pressed={ weatherDayPeriod === 'night' } onClick={ () => setWeatherDayPeriod( 'night' ) }>Night</button>
                                      </div>
                                      { ( () => {
                                        const period = weatherDayPeriod === 'night' ? day.nightDetails : day.dayDetails;
                                        const periodIcon = weatherDayPeriod === 'night' ? day.nightIcon : day.icon;
                                        const periodCondition = weatherDayPeriod === 'night' ? day.nightCondition : day.condition;
                                        const bits: { k: string; v: string; translate?: boolean }[] = [];
                                        if ( Number.isFinite( day.feelsLikeMin ) && Number.isFinite( day.feelsLikeMax ) ) bits.push( { k: 'Feels', v: `${day.feelsLikeMin}°–${day.feelsLikeMax}°` } );
                                        if ( Number.isFinite( period?.humidity ) ) bits.push( { k: 'Humidity', v: `${period?.humidity}%` } );
                                        if ( Number.isFinite( period?.uv ) ) bits.push( { k: 'UV', v: `${period?.uv}` } );
                                        if ( Number.isFinite( period?.rainProb ) ) bits.push( { k: 'Rain chance', v: `${period?.rainProb}%` } );
                                        if ( Number.isFinite( period?.rainMm ) ) bits.push( { k: 'Rain', v: `${period?.rainMm} mm` } );
                                        if ( Number.isFinite( period?.stormProb ) && ( period?.stormProb as number ) > 0 ) bits.push( { k: 'Storm', v: `${period?.stormProb}%` } );
                                        if ( Number.isFinite( period?.windSpeed ) ) bits.push( { k: 'Wind', v: `${period?.windSpeed} ${period?.windUnit || 'km/h'}${period?.windDir ? ` ${period.windDir}` : ''}` } );
                                        if ( Number.isFinite( period?.windGust ) ) bits.push( { k: 'Gust', v: `${period?.windGust} ${period?.windUnit || 'km/h'}` } );
                                        if ( period?.precipitationType ) bits.push( { k: 'Precipitation', v: period.precipitationType.replace( /_/g, ' ' ), translate: true } );
                                        if ( Number.isFinite( period?.pressureHpa ) ) bits.push( { k: 'Pressure', v: `${period?.pressureHpa} mb` } );
                                        if ( Number.isFinite( period?.cloudCover ) ) bits.push( { k: 'Cloud', v: `${period?.cloudCover}%` } );
                                        if ( Number.isFinite( period?.visibilityKm ) ) bits.push( { k: 'Visibility', v: `${period?.visibilityKm} km` } );
                                        if ( Number.isFinite( period?.heatIndex ) ) bits.push( { k: 'Heat index', v: `${period?.heatIndex}°` } );
                                        if ( Number.isFinite( period?.windChill ) ) bits.push( { k: 'Wind chill', v: `${period?.windChill}°` } );
                                        if ( Number.isFinite( day.iceThicknessMm ) && ( day.iceThicknessMm as number ) > 0 ) bits.push( { k: 'Ice', v: `${day.iceThicknessMm} mm` } );
                                        if ( weatherDayPeriod === 'day' && day.sunrise ) bits.push( { k: 'Sunrise', v: formatHistoryPointLabel( new Date( day.sunrise ).getTime(), displayTimeZoneId, locationZoneLabel ) } );
                                        if ( weatherDayPeriod === 'day' && day.sunset ) bits.push( { k: 'Sunset', v: formatHistoryPointLabel( new Date( day.sunset ).getTime(), displayTimeZoneId, locationZoneLabel ) } );
                                        if ( weatherDayPeriod === 'night' && day.moonrise ) bits.push( { k: 'Moonrise', v: formatHistoryPointLabel( new Date( day.moonrise ).getTime(), displayTimeZoneId, locationZoneLabel ) } );
                                        if ( weatherDayPeriod === 'night' && day.moonset ) bits.push( { k: 'Moonset', v: formatHistoryPointLabel( new Date( day.moonset ).getTime(), displayTimeZoneId, locationZoneLabel ) } );
                                        if ( weatherDayPeriod === 'night' && day.moonPhase ) bits.push( { k: 'Moon', v: moonPhaseLabel( day.moonPhase ), translate: true } );
                                        return (
                                          <>
                                            { ( periodIcon || periodCondition ) && (
                                              <div className="vl-live-wx-period-summary">
                                                { periodIcon && <img src={ `${periodIcon}.png` } alt="" aria-hidden="true" data-wc-no-translate="true" /> }
                                                { periodCondition && <strong>{ periodCondition }</strong> }
                                              </div>
                                            ) }
                                            <div className="vl-live-air-forecast-detail">
                                              { bits.map( bit => <span key={ bit.k }><strong>{ bit.k }</strong>{' '}{ bit.translate ? bit.v : <span data-wc-no-translate="true">{ bit.v }</span> }</span> ) }
                                            </div>
                                          </>
                                        );
                                      } )() }
                                    </div>
                                  ) }
                                </li>
                              ) ) }
                            </ul>
                          </div>
                        ) }

                        {/* LAST 24 HOURS - weather history with a metric toggle. */}
                        { weatherHistory.length > 0 && (
                          <div className="vl-live-wx-history">
                            <div className="vl-live-air-forecast-head">
                              <h2 className="vl-live-air-forecast-title">Last 24 Hours</h2>
                              <div className="vl-live-air-range" role="group" aria-label="Weather history metric">
                                { ( [ [ 'temp', 'Temp' ], [ 'rain', 'Rain' ], [ 'humidity', 'Humidity' ], [ 'pressure', 'Pressure' ], [ 'wind', 'Wind' ], [ 'cloud', 'Cloud' ] ] as const ).map( ( [ metric, label ] ) => (
                                  <VayuLokCompactPill key={ metric } className={ weatherHistMetric === metric ? 'is-active' : '' } aria-pressed={ weatherHistMetric === metric } onClick={ () => setWeatherHistMetric( metric ) }>
                                    { label }
                                  </VayuLokCompactPill>
                                ) ) }
                              </div>
                            </div>
                            <ul className="vl-live-wx-hist-strip" aria-label="Last 24 hours">
                              { weatherHistory.map( ( hour, idx ) => {
                                const value = weatherHistMetric === 'temp' ? ( Number.isFinite( hour.temp ) ? `${hour.temp}°` : '' )
                                  : weatherHistMetric === 'rain' ? ( Number.isFinite( hour.rainMm ) ? `${hour.rainMm} mm` : Number.isFinite( hour.rainProb ) ? `${hour.rainProb}%` : '' )
                                    : weatherHistMetric === 'humidity' ? ( Number.isFinite( hour.humidity ) ? `${hour.humidity}%` : '' )
                                      : weatherHistMetric === 'pressure' ? ( Number.isFinite( hour.pressureHpa ) ? `${hour.pressureHpa} mb` : '' )
                                        : weatherHistMetric === 'wind' ? ( Number.isFinite( hour.windSpeed ) ? `${hour.windSpeed} ${hour.windUnit || 'km/h'}` : '' )
                                          : ( Number.isFinite( hour.cloudCover ) ? `${hour.cloudCover}%` : '' );
                                return (
                                  <li key={ hour.time } className="vl-live-wx-hist-slot">
                                    <button
                                      type="button"
                                      className={ `vl-live-wx-hist-item ${weatherHistoryInspectIdx === idx ? 'is-active' : ''}`.trim() }
                                      aria-pressed={ weatherHistoryInspectIdx === idx }
                                      onClick={ () => setWeatherHistoryInspectIdx( weatherHistoryInspectIdx === idx ? null : idx ) }
                                    >
                                      <span className="vl-live-wx-hist-t" data-wc-no-translate="true">{ formatHistoryPointLabel( hour.time, displayTimeZoneId, locationZoneLabel ) }</span>
                                      <span className="vl-live-wx-hist-v" data-wc-no-translate="true">{ value }</span>
                                    </button>
                                  </li>
                                );
                              } ) }
                            </ul>
                            { weatherHistoryInspectIdx != null && weatherHistory[ weatherHistoryInspectIdx ] && (
                              <div className="vl-live-air-forecast-detail">
                                { ( () => {
                                  const h = weatherHistory[ weatherHistoryInspectIdx ];
                                  const bits: { k: string; v: string; raw?: boolean }[] = [];
                                  if ( h.condition ) bits.push( { k: 'Condition', v: h.condition } );
                                  if ( Number.isFinite( h.temp ) ) bits.push( { k: 'Temp', v: `${h.temp}°`, raw: true } );
                                  if ( Number.isFinite( h.feelsLike ) ) bits.push( { k: 'Feels', v: `${h.feelsLike}°`, raw: true } );
                                  if ( Number.isFinite( h.humidity ) ) bits.push( { k: 'Humidity', v: `${h.humidity}%`, raw: true } );
                                  if ( Number.isFinite( h.dewPoint ) ) bits.push( { k: 'Dew point', v: `${h.dewPoint}°`, raw: true } );
                                  if ( Number.isFinite( h.heatIndex ) ) bits.push( { k: 'Heat index', v: `${h.heatIndex}°`, raw: true } );
                                  if ( Number.isFinite( h.wetBulb ) ) bits.push( { k: 'Wet bulb', v: `${h.wetBulb}°`, raw: true } );
                                  if ( Number.isFinite( h.windChill ) ) bits.push( { k: 'Wind chill', v: `${h.windChill}°`, raw: true } );
                                  if ( Number.isFinite( h.rainProb ) ) bits.push( { k: 'Rain', v: `${h.rainProb}%${Number.isFinite( h.rainMm ) ? ` · ${h.rainMm} mm` : ''}`, raw: true } );
                                  if ( h.precipitationType ) bits.push( { k: 'Precipitation', v: h.precipitationType.replace( /_/g, ' ' ) } );
                                  if ( Number.isFinite( h.stormProb ) ) bits.push( { k: 'Storm', v: `${h.stormProb}%`, raw: true } );
                                  if ( Number.isFinite( h.pressureHpa ) ) bits.push( { k: 'Pressure', v: `${h.pressureHpa} mb`, raw: true } );
                                  if ( Number.isFinite( h.windSpeed ) ) bits.push( { k: 'Wind', v: `${h.windSpeed} ${h.windUnit || 'km/h'}${h.windDir ? ` ${h.windDir}` : ''}`, raw: true } );
                                  if ( Number.isFinite( h.windGust ) ) bits.push( { k: 'Gust', v: `${h.windGust} ${h.windUnit || 'km/h'}`, raw: true } );
                                  if ( Number.isFinite( h.visibilityKm ) ) bits.push( { k: 'Visibility', v: `${h.visibilityKm} km`, raw: true } );
                                  if ( Number.isFinite( h.cloudCover ) ) bits.push( { k: 'Cloud', v: `${h.cloudCover}%`, raw: true } );
                                  if ( Number.isFinite( h.iceThicknessMm ) && ( h.iceThicknessMm as number ) > 0 ) bits.push( { k: 'Ice', v: `${h.iceThicknessMm} mm`, raw: true } );
                                  return bits.map( b => (
                                    <span key={ b.k }><strong>{ b.k }</strong>{' '}
                                      { b.raw ? <span data-wc-no-translate="true">{ b.v }</span> : b.v }
                                    </span>
                                  ) );
                                } )() }
                              </div>
                            ) }
                          </div>
                        ) }
                        { weatherHistoryFetchedAt && ( () => {
                          const age = relativeAgeLabel( weatherHistoryFetchedAt );
                          return (
                            <div className="vl-live-wx-freshness vl-live-freshness" aria-label={ `History ${age.label.toLowerCase()}` }>
                              <svg className="vl-live-freshness-icon" viewBox="0 -960 960 960" aria-hidden="true"><path d={ MATERIAL_SYMBOL_PATHS.schedule } /></svg>
                              <span>{ freshnessTimeLabel( age.label ) }</span>
                            </div>
                          );
                        } )() }

                        <VayuLokWeatherInsights
                          lat={ place.lat }
                          lng={ place.lng }
                          placeName={ place.name }
                          timeZoneId={ locationTime.timeZoneId }
                          zoneLabel={ locationZoneLabel }
                          includeUiStyles={ false }
                        />

                        { weather.currentTime && <span className="vl-live-sr-only">Weather updated for the selected place.</span> }
                      </>
                    ) : (
                      <p className="vl-live-air-empty" role="status">{ dataLoading ? 'Loading weather…' : hasSelection ? 'Weather unavailable.' : 'Choose a place for weather.' }</p>
                    ) }
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
                  <strong>{ previewPlace.name || 'New Delhi' }</strong>
                  { previewPlace.addr && <span>{ previewPlace.addr }</span> }
                  <p>{ mapActive ? 'Could not load map' : 'Map unavailable' }</p>
                  { mapActive && mapFailed && (
                    <button
                      type="button"
                      className="vl-live-map-retry"
                      onClick={ () => { setMapFailed( false ); setMapVisible( false ); setMapReady( false ); setMapInitNonce( n => n + 1 ); } }
                    >
                      Try again
                    </button>
                  ) }
                </div>
              ) : (
                <>
                  { !mapVisible && (
                    <div className="vl-live-map-fallback" role="status" aria-label="Loading map">
                      <span className="vl-live-map-loading-dot" aria-hidden="true" />
                    </div>
                  ) }
                  <div className={ `vl-live-map-canvas ${mapVisible ? 'is-ready' : ''}` } ref={ mapHost } role="img" aria-label={ hasSelection ? `Map of ${place.name}` : 'Interactive world map' } />
                </>
              ) }



            </div>
          </section>
        </div>

        <section className="vl-live-tools" aria-labelledby="vl-live-tools-title">
          <div className="vl-live-tools-layout">
            <div className="vl-live-tools-left">
              <div className="vl-live-tools-head">
                <h2 id="vl-live-tools-title" className="vl-live-card-title">Local time &amp; currency</h2>
                <p>Compare time zones and reference exchange rates.</p>
              </div>

              <article className="vl-live-tool-card is-primary-tool" aria-label="Time and currency tools">
              <div className="vl-live-tool-toggle" role="tablist" aria-label="Local time or currency">
                <button
                  type="button"
                  role="tab"
                  id="vl-live-tool-time-tab"
                  aria-controls={ toolTab === 'time' ? 'vl-live-tool-time-panel' : undefined }
                  aria-selected={ toolTab === 'time' }
                  className={ `vl-live-tool-toggle-btn is-time ${toolTab === 'time' ? 'is-active' : ''}`.trim() }
                  onClick={ () => setToolTab( 'time' ) }
                >
                  <i className="vl-live-tool-toggle-dot" aria-hidden="true" />Local time
                </button>
                <button
                  type="button"
                  role="tab"
                  id="vl-live-tool-currency-tab"
                  aria-controls={ toolTab === 'currency' ? 'vl-live-tool-currency-panel' : undefined }
                  aria-selected={ toolTab === 'currency' }
                  className={ `vl-live-tool-toggle-btn is-currency ${toolTab === 'currency' ? 'is-active' : ''}`.trim() }
                  onClick={ () => setToolTab( 'currency' ) }
                >
                  <i className="vl-live-tool-toggle-dot" aria-hidden="true" />Currency
                </button>
              </div>

              { toolTab === 'time' && (
                <div className="vl-live-tool-panel" role="tabpanel" id="vl-live-tool-time-panel" aria-labelledby="vl-live-tool-time-tab">
                  <h3>Compare local time</h3>
                  <div className="vl-live-world-pair">
                    <div className="vl-live-world-place">
                      <span>From place</span>
                      <div className="vl-live-utility-search">
                        <input
                          id="vl-live-world-from"
                          type="search"
                          role="combobox"
                          value={ utilityQueries[ 'world-from' ] }
                          onChange={ e => onUtilityQueryChange( 'world-from', e.target.value ) }
                          onFocus={ () => {
                            void ensurePlacesLibrary();
                            const value = utilityQueries[ 'world-from' ];
                            if ( value.trim().length >= WORLD_SEARCH_MIN_CHARS ) void runUtilityPlaceSearch( 'world-from', value );
                          } }
                          onKeyDown={ e => onUtilityKeyDown( 'world-from', e ) }
                          aria-label="World time from place"
                          // ARIA 1.2: a combobox needs aria-controls only while its popup is
                          // shown, and the listbox is rendered only then.
                          aria-controls={ utilityOpenSlot === 'world-from' && utilityResults.length > 0 ? 'vl-live-world-from-results' : undefined }
                          aria-autocomplete="list"
                          aria-expanded={ utilityOpenSlot === 'world-from' && utilityResults.length > 0 }
                          aria-activedescendant={ utilityOpenSlot === 'world-from' && utilityActive >= 0 ? `vl-live-world-from-option-${utilityActive}` : undefined }
                          placeholder="Search city or pincode"
                          autoComplete="off"
                          autoCorrect="off"
                          spellCheck={ false }
                        />
                        <VoiceSearchMic ariaLabel="Search world time from place by voice" onTranscript={ transcript => onUtilityVoice( 'world-from', transcript ) } />
                        { utilityOpenSlot === 'world-from' && utilityResults.length > 0 && (
                          <ul className="vl-live-utility-results" id="vl-live-world-from-results" role="listbox" aria-label="World time from places">
                            { utilityResults.map( ( result, idx ) => (
                              <li key={ `world-from-${result.name}-${result.addr}-${idx}` } id={ `vl-live-world-from-option-${idx}` } role="option" aria-selected={ utilityActive === idx } className={ utilityActive === idx ? 'is-active' : '' } onPointerDown={ e => { e.preventDefault(); void chooseUtilityPlace( 'world-from', result ); } } onMouseEnter={ () => setUtilityActive( idx ) }>
                                <strong>{ result.name }</strong>{ result.addr && <small>{ result.addr }</small> }
                              </li>
                            ) ) }
                          </ul>
                        ) }
                        { utilityOpenSlot === 'world-from' && utilitySearchStatus === 'searching' && <span className="vl-live-sr-only" role="status">Searching places…</span> }
                        { utilityOpenSlot === 'world-from' && utilitySearchStatus === 'no-results' && <span className="vl-live-utility-empty" role="status">Place not found.</span> }
                        { utilityOpenSlot === 'world-from' && utilitySearchStatus === 'unavailable' && <span className="vl-live-utility-empty" role="status">Search unavailable.</span> }
                      </div>
                      <strong>{ worldFrom.name }</strong>
                      <small className="vl-live-place-selection">{ worldFrom.addr }</small>
                      { worldFrom.clock && <b data-wc-no-translate="true" suppressHydrationWarning>{ worldFrom.clock } · { worldFrom.zone }</b> }
                      { worldFrom.date && <small data-wc-no-translate="true" suppressHydrationWarning>{ worldFrom.date }</small> }
                    </div>

                    <button type="button" className="vl-live-tool-swap" onClick={ swapWorldPlaces } aria-label="Swap displayed time zones">⇅</button>

                    <div className="vl-live-world-place">
                      <span>To place</span>
                      <div className="vl-live-utility-search">
                        <input
                          id="vl-live-world-to"
                          type="search"
                          role="combobox"
                          value={ utilityQueries[ 'world-to' ] }
                          onChange={ e => onUtilityQueryChange( 'world-to', e.target.value ) }
                          onFocus={ () => {
                            void ensurePlacesLibrary();
                            const value = utilityQueries[ 'world-to' ];
                            if ( value.trim().length >= WORLD_SEARCH_MIN_CHARS ) void runUtilityPlaceSearch( 'world-to', value );
                          } }
                          onKeyDown={ e => onUtilityKeyDown( 'world-to', e ) }
                          aria-label="World time to place"
                          aria-controls={ utilityOpenSlot === 'world-to' && utilityResults.length > 0 ? 'vl-live-world-to-results' : undefined }
                          aria-autocomplete="list"
                          aria-expanded={ utilityOpenSlot === 'world-to' && utilityResults.length > 0 }
                          aria-activedescendant={ utilityOpenSlot === 'world-to' && utilityActive >= 0 ? `vl-live-world-to-option-${utilityActive}` : undefined }
                          placeholder="Search city or pincode"
                          autoComplete="off"
                          autoCorrect="off"
                          spellCheck={ false }
                        />
                        <VoiceSearchMic ariaLabel="Search world time to place by voice" onTranscript={ transcript => onUtilityVoice( 'world-to', transcript ) } />
                        { utilityOpenSlot === 'world-to' && utilityResults.length > 0 && (
                          <ul className="vl-live-utility-results" id="vl-live-world-to-results" role="listbox" aria-label="World time to places">
                            { utilityResults.map( ( result, idx ) => (
                              <li key={ `world-to-${result.name}-${result.addr}-${idx}` } id={ `vl-live-world-to-option-${idx}` } role="option" aria-selected={ utilityActive === idx } className={ utilityActive === idx ? 'is-active' : '' } onPointerDown={ e => { e.preventDefault(); void chooseUtilityPlace( 'world-to', result ); } } onMouseEnter={ () => setUtilityActive( idx ) }>
                                <strong>{ result.name }</strong>{ result.addr && <small>{ result.addr }</small> }
                              </li>
                            ) ) }
                          </ul>
                        ) }
                        { utilityOpenSlot === 'world-to' && utilitySearchStatus === 'searching' && <span className="vl-live-sr-only" role="status">Searching places…</span> }
                        { utilityOpenSlot === 'world-to' && utilitySearchStatus === 'no-results' && <span className="vl-live-utility-empty" role="status">Place not found.</span> }
                        { utilityOpenSlot === 'world-to' && utilitySearchStatus === 'unavailable' && <span className="vl-live-utility-empty" role="status">Search unavailable.</span> }
                      </div>
                      <strong>{ worldTo.name }</strong>
                      <small className="vl-live-place-selection">{ worldTo.addr }</small>
                      { worldTo.clock && <b data-wc-no-translate="true" suppressHydrationWarning>{ worldTo.clock } · { worldTo.zone }</b> }
                      { worldTo.date && <small data-wc-no-translate="true" suppressHydrationWarning>{ worldTo.date }</small> }
                    </div>
                  </div>
                </div>
              ) }

              { toolTab === 'currency' && (
                <div className="vl-live-tool-panel" role="tabpanel" id="vl-live-tool-currency-panel" aria-labelledby="vl-live-tool-currency-tab">
                  <h3>Currency rate</h3>
                  <div className="vl-live-fx-pair" aria-label="Currency pair">
                    <div className="vl-live-utility-search vl-live-fx-search">
                      <input
                        type="search"
                        role="combobox"
                        value={ fxBaseInput }
                        onChange={ e => onCurrencyInputChange( 'base', e.target.value ) }
                        onFocus={ e => {
                          setCurrencyOpenSide( 'base' );
                          setCurrencyActive( 0 );
                          e.currentTarget.select();
                        } }
                        onBlur={ () => normalizeCurrencyInput( 'base' ) }
                        onKeyDown={ e => onCurrencyKeyDown( 'base', e ) }
                        aria-label="Base currency"
                        aria-controls={ currencyOpenSide === 'base' && currencySuggestions.length > 0 ? 'vl-live-fx-base-results' : undefined }
                        aria-autocomplete="list"
                        aria-expanded={ currencyOpenSide === 'base' && currencySuggestions.length > 0 }
                        aria-activedescendant={ currencyOpenSide === 'base' && currencySuggestions.length ? `vl-live-fx-base-option-${currencyActive}` : undefined }
                        placeholder="Search currency"
                        autoComplete="off"
                        autoCorrect="off"
                        spellCheck={ false }
                      />
                      { currencyOpenSide === 'base' && currencySuggestions.length > 0 && (
                        <ul className="vl-live-utility-results" id="vl-live-fx-base-results" role="listbox" aria-label="Available base currencies">
                          { currencySuggestions.map( ( code, idx ) => (
                            <li
                              key={ `base-${code}` }
                              id={ `vl-live-fx-base-option-${idx}` }
                              role="option"
                              aria-selected={ currencyActive === idx }
                              className={ currencyActive === idx ? 'is-active' : '' }
                              onPointerDown={ e => { e.preventDefault(); chooseCurrency( 'base', code ); } }
                              onMouseEnter={ () => setCurrencyActive( idx ) }
                            >
                              <strong data-wc-no-translate="true">{ code }</strong>
                            </li>
                          ) ) }
                        </ul>
                      ) }
                      { currencyOpenSide === 'base' && !currencySuggestions.length && (
                        <span className="vl-live-utility-empty" role="status">Currency unavailable.</span>
                      ) }
                    </div>

                    <button type="button" className="vl-live-tool-swap is-horizontal" onClick={ swapFxPair } aria-label="Swap currencies">⇄</button>

                    <div className="vl-live-utility-search vl-live-fx-search">
                      <input
                        type="search"
                        role="combobox"
                        value={ fxQuoteInput }
                        onChange={ e => onCurrencyInputChange( 'quote', e.target.value ) }
                        onFocus={ e => {
                          setCurrencyOpenSide( 'quote' );
                          setCurrencyActive( 0 );
                          e.currentTarget.select();
                        } }
                        onBlur={ () => normalizeCurrencyInput( 'quote' ) }
                        onKeyDown={ e => onCurrencyKeyDown( 'quote', e ) }
                        aria-label="Quote currency"
                        aria-controls={ currencyOpenSide === 'quote' && currencySuggestions.length > 0 ? 'vl-live-fx-quote-results' : undefined }
                        aria-autocomplete="list"
                        aria-expanded={ currencyOpenSide === 'quote' && currencySuggestions.length > 0 }
                        aria-activedescendant={ currencyOpenSide === 'quote' && currencySuggestions.length ? `vl-live-fx-quote-option-${currencyActive}` : undefined }
                        placeholder="Search currency"
                        autoComplete="off"
                        autoCorrect="off"
                        spellCheck={ false }
                      />
                      { currencyOpenSide === 'quote' && currencySuggestions.length > 0 && (
                        <ul className="vl-live-utility-results" id="vl-live-fx-quote-results" role="listbox" aria-label="Available quote currencies">
                          { currencySuggestions.map( ( code, idx ) => (
                            <li
                              key={ `quote-${code}` }
                              id={ `vl-live-fx-quote-option-${idx}` }
                              role="option"
                              aria-selected={ currencyActive === idx }
                              className={ currencyActive === idx ? 'is-active' : '' }
                              onPointerDown={ e => { e.preventDefault(); chooseCurrency( 'quote', code ); } }
                              onMouseEnter={ () => setCurrencyActive( idx ) }
                            >
                              <strong data-wc-no-translate="true">{ code }</strong>
                            </li>
                          ) ) }
                        </ul>
                      ) }
                      { currencyOpenSide === 'quote' && !currencySuggestions.length && (
                        <span className="vl-live-utility-empty" role="status">Currency unavailable.</span>
                      ) }
                    </div>
                  </div>

                  <div className="vl-live-fx-result" aria-live="polite">
                    { fxLoading ? (
                      <span>Loading reference rate…</span>
                    ) : fxError ? (
                      <span>Reference rate is temporarily unavailable.</span>
                    ) : fxRate && fxRate.base === fxBase && fxRate.quote === fxQuote ? (
                      <>
                        <strong data-wc-no-translate="true">
                          1 { fxBase } = { fxRate.rate.toLocaleString( 'en-IN', { maximumFractionDigits: 6 } ) } { fxQuote }
                        </strong>
                        <small data-wc-no-translate="true">{ fxRate.date ? `Latest reference rate · ${fxRate.date}` : 'Latest reference rate' }</small>
                      </>
                    ) : (
                      <span>Select currencies to load the reference rate.</span>
                    ) }
                  </div>
                </div>
              ) }
              </article>
            </div>
            <div className="vl-live-tools-right">
              <div className="vl-live-tools-head">
                <h2 className="vl-live-card-title">Route</h2>
                <p>Time and distance, at a glance.</p>
              </div>

              <article className="vl-live-tool-card is-route-tool" aria-label="Route tool">
                <div className="vl-live-tool-panel">
                  <div className="vl-live-route-pair">
                    { ( [ 'route-from', 'route-to' ] as const ).map( slot => {
                      const selected = slot === 'route-from' ? routeFrom : routeTo;
                      const label = slot === 'route-from' ? 'From place' : 'To place';
                      const resultId = `vl-live-${slot}-results`;
                      return (
                        <React.Fragment key={ slot }>
                          <div className="vl-live-route-place">
                          <span>{ label }</span>
                          <div className="vl-live-utility-search">
                            <input
                              type="search"
                              role="combobox"
                              value={ utilityQueries[ slot ] }
                              onChange={ e => onUtilityQueryChange( slot, e.target.value ) }
                              onFocus={ () => {
                                void ensurePlacesLibrary();
                                const value = utilityQueries[ slot ];
                                if ( value.trim().length >= WORLD_SEARCH_MIN_CHARS ) void runUtilityPlaceSearch( slot, value );
                              } }
                              onKeyDown={ e => onUtilityKeyDown( slot, e ) }
                              aria-label={ `${label} for route` }
                              aria-controls={ utilityOpenSlot === slot && utilityResults.length > 0 ? resultId : undefined }
                              aria-autocomplete="list"
                              aria-expanded={ utilityOpenSlot === slot && utilityResults.length > 0 }
                              aria-activedescendant={ utilityOpenSlot === slot && utilityActive >= 0 ? `${resultId}-option-${utilityActive}` : undefined }
                              placeholder="Search city or pincode"
                              autoComplete="off"
                              autoCorrect="off"
                              spellCheck={ false }
                            />
                            <VoiceSearchMic ariaLabel={ `Search ${label.toLowerCase()} by voice` } onTranscript={ transcript => onUtilityVoice( slot, transcript ) } />
                            { utilityOpenSlot === slot && utilityResults.length > 0 && (
                              <ul className="vl-live-utility-results" id={ resultId } role="listbox" aria-label={ `${label} suggestions` }>
                                { utilityResults.map( ( result, idx ) => (
                                  <li
                                    key={ `${slot}-${result.name}-${result.addr}-${idx}` }
                                    id={ `${resultId}-option-${idx}` }
                                    role="option"
                                    aria-selected={ utilityActive === idx }
                                    className={ utilityActive === idx ? 'is-active' : '' }
                                    onPointerDown={ e => { e.preventDefault(); void chooseUtilityPlace( slot, result ); } }
                                    onMouseEnter={ () => setUtilityActive( idx ) }
                                  >
                                    <strong>{ result.name }</strong>{ result.addr && <small>{ result.addr }</small> }
                                  </li>
                                ) ) }
                              </ul>
                            ) }
                            { utilityOpenSlot === slot && utilitySearchStatus === 'searching' && <span className="vl-live-sr-only" role="status">Searching places…</span> }
                            { utilityOpenSlot === slot && utilitySearchStatus === 'no-results' && <span className="vl-live-utility-empty" role="status">Place not found.</span> }
                            { utilityOpenSlot === slot && utilitySearchStatus === 'unavailable' && <span className="vl-live-utility-empty" role="status">Search unavailable.</span> }
                          </div>
                          { selected && (
                            <>
                              <strong>{ selected.name }</strong>
                              <small>{ selected.addr }</small>
                            </>
                          ) }
                          </div>
                          { slot === 'route-from' && (
                            <button type="button" className="vl-live-route-swap" onClick={ swapRoutePlaces } aria-label="Swap route places">⇄</button>
                          ) }
                        </React.Fragment>
                      );
                    } ) }
                  </div>

                  <div className="vl-live-route-result" aria-live="polite">
                    <button
                      type="button"
                      className="vl-live-route-check"
                      disabled={ !ROUTE_REQUEST_ENABLED || !routeFrom || !routeTo || routeLoading }
                      onClick={ () => { void checkRoute(); } }
                    >
                      { routeLoading ? 'Checking route…' : 'Check route' }
                    </button>
                    { !ROUTE_REQUEST_ENABLED ? (
                      <span className="vl-live-route-unavailable" role="status">Route unavailable.</span>
                    ) : routeError ? (
                      <span className="vl-live-route-unavailable" role="status">Route unavailable.</span>
                    ) : null }
                    { routeResult && routeFrom && routeTo && (
                      <div className="vl-live-route-metrics">
                        <div>
                          <span>Driving time</span>
                          <strong data-wc-no-translate="true">{ routeDurationLabel( routeResult.durationSeconds ) }</strong>
                        </div>
                        <div>
                          <span>Driving distance</span>
                          <strong data-wc-no-translate="true">{ routeDistanceLabel( routeResult.distanceMeters ) }</strong>
                        </div>
                        <div>
                          <span>Direct distance</span>
                          <strong data-wc-no-translate="true">{ directDistanceKm( routeFrom, routeTo ).toFixed( 1 ) } km</strong>
                        </div>
                      </div>
                    ) }
                  </div>
                </div>
              </article>
            </div>
          </div>
        </section>
      </div>

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
                <span>{ shortAirInfo( activePollutant.sources ) }</span>
              </div>
            ) }
            { activePollutant.effects && (
              <div className="vl-live-air-pollutant-pop-line is-effect">
                <strong>Effects</strong>
                <span>{ shortAirInfo( activePollutant.effects ) }</span>
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
          --page:var(--public-bg);--lime:var(--public-brand-lime);--lime-tint:var(--public-lime-tint);--vl-surface:#fff;--vl-hover-bg:var(--lime-tint);--vl-active-bg:var(--lime);--vl-hover-shadow:0 4px 12px rgba(26,58,42,.10);
          font-family:var(--font-sans);
          --green:var(--public-brand-green);--hair:var(--public-hairline);--heading:var(--public-heading);--body:var(--public-body);
          --muted:var(--public-muted);--status:rgba(0,0,0,.70);
          /* Corner radii source from the shared homepage tokens (src/styles/tokens.css) so
             VayuLok's cards, controls and the map shell match the rest of the site rather than
             carrying their own hard-coded values. Fallbacks keep the component self-contained if
             the tokens are ever absent. --panel-r (cards/panels) = --radius-xl (14px),
             --pill-r (pills/toggles) = --radius-full. */
          --panel-r:var(--radius-xl,14px);--pill-r:var(--radius-full,999px);
          /* Shared VayuLok UI system, pinned to the homepage card/body ladder. */
          --vl-card-heading-size:var(--public-card-size);--vl-card-heading-weight:var(--public-card-weight);--vl-card-heading-lh:var(--public-card-leading);--vl-card-heading-track:var(--public-card-tracking);
          --vl-body-size:var(--public-body-size);--vl-body-weight:var(--public-body-weight);--vl-body-lh:var(--public-body-leading);--vl-body-track:var(--public-body-tracking);
          /* Deep typography audit: every visible VayuLok role below resolves to the canonical
             Home/public ladder. Compact panel headings deliberately use the 17px data rung (the
             same visual scale as compact readings such as "Feels 17°"); narrative/tool headings
             keep the Home card/body rungs, while metadata stays on the 14px public meta rung. */
          --vl-panel-heading-size:var(--public-data-size);--vl-panel-heading-weight:700;--vl-panel-heading-lh:1.35;--vl-panel-heading-track:-.18px;
          --vl-data-size:var(--public-data-size);--vl-subtext-size:var(--public-supporting-size);--vl-meta-size:var(--public-meta-size);--vl-control-size:var(--public-cta-font-size);--vl-control-weight:var(--public-cta-font-weight);--vl-metric-size:var(--public-section-size);--vl-compact-copy-size:var(--vl-subtext-size);
          --vl-section-gap:24px;--vl-section-pad:20px;--vl-heading-gap:14px;--vl-content-gap:16px;--vl-action-size:var(--tap-min);
          font-family:var(--font-sans);color:var(--body);background:var(--page);padding-bottom:72px;-webkit-font-smoothing:antialiased;
        }
        .vl-live,.vl-live *{box-sizing:border-box}
        .vl-live button,.vl-live input{font:inherit}
        .vl-live button{cursor:pointer}
        .vl-live button:focus-visible{outline:3px solid var(--green);outline-offset:3px}
        .vl-live input:focus-visible{outline:none}
        .vl-live-sr,.vl-live-sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
        .vl-live-shell{max-width:1320px;margin:0 auto;padding:0 max(var(--public-page-gutter),var(--safe-right)) max(72px,var(--safe-bottom)) max(var(--public-page-gutter),var(--safe-left))}
        /* The map is now the full-width backdrop; the former two-column workspace
           collapses to a single region that the map shell fills edge to edge. */
        .vl-live-workspace{display:block}
        .vl-live-map-region{min-width:0}

        .vl-live-tools{margin-top:28px;padding-top:28px;border-top:1px solid var(--hair)}
        .vl-live-tools-layout{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:stretch;gap:48px}
        .vl-live-tools-left,.vl-live-tools-right{display:flex;min-width:0;flex-direction:column}
        .vl-live-tools-head{display:flex;flex-direction:column;align-items:flex-start;gap:6px;margin-bottom:16px}
        .vl-live-tools-head h2{margin:0;color:var(--heading);font-size:var(--vl-card-heading-size);font-weight:var(--vl-card-heading-weight);line-height:var(--vl-card-heading-lh);letter-spacing:var(--vl-card-heading-track)}
        .vl-live-tools-head p{max-width:520px;margin:0;color:var(--body);font-size:var(--vl-body-size);font-weight:var(--vl-body-weight);line-height:var(--vl-body-lh);letter-spacing:var(--vl-body-track)}
        .vl-live-tool-card{position:relative;min-width:0;flex:1;padding:24px;border:1px solid var(--hair);border-radius:var(--panel-r);background:#fff;filter:none}
        .vl-live-tool-toggle{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:4px;border:1px solid var(--hair);border-radius:var(--pill-r);background:#fff;box-shadow:0 6px 18px rgba(26,58,42,.08)}
        .vl-live-tool-toggle-btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:var(--tap-min);border:0;border-radius:var(--pill-r);background:transparent;color:var(--green);font-size:var(--vl-subtext-size);font-weight:700;line-height:1;letter-spacing:0}
        .vl-live-tool-toggle-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:rgba(26,58,42,.3)}
        .vl-live-tool-toggle-btn.is-active{background:var(--lime);color:var(--green)}
        .vl-live-tool-toggle-btn.is-active .vl-live-tool-toggle-dot{background:var(--green)}
        .vl-live-tool-panel{margin-top:var(--vl-section-gap)}
        .vl-live-tool-panel>h3{margin:0;color:var(--heading);font-size:var(--vl-card-heading-size);font-weight:var(--vl-card-heading-weight);line-height:var(--vl-card-heading-lh);letter-spacing:var(--vl-card-heading-track);padding-inline-start:10px;border-inline-start:3px solid var(--lime)}

        .vl-live-world-pair,.vl-live-fx-pair{display:grid;grid-template-columns:minmax(0,1fr) var(--vl-action-size) minmax(0,1fr);align-items:start;gap:12px;margin-top:var(--vl-heading-gap)}
        .vl-live-world-place{display:flex;min-width:0;flex-direction:column;gap:4px}
        .vl-live-world-place>span{color:var(--muted);font-size:var(--vl-meta-size);font-weight:700;letter-spacing:.08em;text-transform:uppercase}
        .vl-live-utility-search{position:relative;min-width:0;height:52px;margin-top:2px}
        .vl-live-utility-search>input{width:100%;height:52px;min-width:0;padding-block:0;padding-inline:2px 44px;border:0;border-bottom:1px solid #e5e7eb;border-radius:0;background:transparent;color:#1a1a1a;font-size:var(--vl-data-size);font-weight:400;font-family:inherit;outline:none;transition:border-color .2s,box-shadow .2s}
        .vl-live-utility-search>input::placeholder{color:var(--public-muted);font-weight:400}
        .vl-live-utility-search>input::-webkit-search-cancel-button,.vl-live-utility-search>input::-webkit-search-decoration{display:none;-webkit-appearance:none}
        .vl-live-utility-search>input::-ms-clear{display:none;width:0;height:0}
        .vl-live-utility-search>input:focus-visible{outline:none;border-bottom-color:#1a3a2a;box-shadow:0 1px 0 0 #d1f470}
        .vl-live-utility-results{position:absolute;z-index:34;top:calc(100% + 7px);inset-inline:0;margin:0;padding:6px;list-style:none;border:1px solid var(--hair);border-radius:var(--radius-lg,12px);background:#fff;box-shadow:none}
        .vl-live-utility-results li{display:flex;flex-direction:column;gap:2px;padding:10px 11px;border-radius:var(--radius-md,10px);cursor:pointer}
        .vl-live-utility-results li.is-active,.vl-live-utility-results li:hover{background:var(--lime-tint)}
        .vl-live-utility-results strong{color:var(--heading);font-size:var(--vl-data-size);font-weight:700}
        .vl-live-utility-results small{color:var(--muted);font-size:var(--vl-subtext-size)}
        .vl-live-utility-empty{position:absolute;top:calc(100% + 7px);inset-inline:0;z-index:33;padding:10px 12px;border:1px solid var(--hair);border-radius:var(--radius-lg,12px);background:#fff;color:var(--muted);font-size:var(--vl-subtext-size);box-shadow:none}
        .vl-live-world-place>strong{overflow:hidden;margin-top:4px;color:var(--heading);font-size:var(--vl-data-size);font-weight:700;line-height:1.25;letter-spacing:-.18px;text-overflow:ellipsis;white-space:nowrap}
        .vl-live-place-selection{overflow:hidden;color:var(--muted);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.4;text-overflow:ellipsis;white-space:nowrap}
        .vl-live-world-place>b{margin-top:3px;color:var(--heading);font-size:var(--vl-data-size);font-weight:700;line-height:1.25;letter-spacing:-.2px;white-space:nowrap}
        .vl-live-world-place>small:not(.vl-live-place-selection){color:var(--muted);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.4}
        .vl-live-tool-swap{align-self:center;display:inline-flex;align-items:center;justify-content:center;width:var(--vl-action-size);height:var(--vl-action-size);margin-top:30px;padding:0;border:0;border-radius:50%;background:var(--lime);color:var(--green);font-size:var(--vl-data-size);font-weight:800;line-height:1}
        .vl-live-tool-swap.is-horizontal{margin-top:8px;font-size:var(--vl-data-size)}

        .vl-live-fx-pair{align-items:center}
        .vl-live-fx-search>input{padding-inline-end:2px;text-transform:uppercase}
        .vl-live-fx-result{display:flex;min-height:82px;flex-direction:column;justify-content:center;gap:6px;margin-top:var(--vl-section-gap);padding-top:var(--vl-section-pad);border-top:1px solid var(--hair)}
        .vl-live-fx-result>strong{color:var(--heading);font-size:var(--vl-card-heading-size);font-weight:var(--vl-card-heading-weight);line-height:var(--vl-card-heading-lh);letter-spacing:var(--vl-card-heading-track)}
        .vl-live-fx-result>small{color:var(--muted);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.4}
        .vl-live-fx-result>span{color:var(--muted);font-size:var(--vl-meta-size);font-weight:600;line-height:1.5}
        .vl-live-route-pair{display:grid;grid-template-columns:minmax(0,1fr) var(--vl-action-size) minmax(0,1fr);align-items:start;gap:12px;margin-top:var(--vl-heading-gap)}
        .vl-live-route-place{display:flex;min-width:0;flex-direction:column;gap:4px}
        .vl-live-route-place>span{color:var(--muted);font-size:var(--vl-meta-size);font-weight:700;letter-spacing:.08em;text-transform:uppercase}
        .vl-live-route-place>strong{overflow:hidden;margin-top:4px;color:var(--heading);font-size:var(--vl-data-size);font-weight:700;line-height:1.25;letter-spacing:-.18px;text-overflow:ellipsis;white-space:nowrap}
        .vl-live-route-place>small{overflow:hidden;color:var(--muted);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.4;text-overflow:ellipsis;white-space:nowrap}
        .vl-live-route-swap{align-self:center;justify-self:center;display:flex;align-items:center;justify-content:center;width:var(--vl-action-size);height:var(--vl-action-size);margin-top:30px;padding:0;border:0;border-radius:50%;background:var(--lime);color:var(--green);font-size:var(--vl-data-size);font-weight:800}
        .vl-live-route-result{display:flex;min-height:82px;flex-direction:column;justify-content:center;gap:12px;margin-top:var(--vl-section-gap);padding-top:var(--vl-section-pad);border-top:1px solid var(--hair)}
        .vl-live-route-result>span{color:var(--muted);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.45}
        .vl-live-route-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
        .vl-live-route-metrics>div{min-width:0;padding:12px 14px;border:1px solid var(--hair);border-radius:var(--radius-lg,12px);background:var(--lime-tint)}
        .vl-live-route-metrics span{display:block;color:var(--muted);font-size:var(--vl-meta-size);font-weight:700;letter-spacing:.06em;text-transform:uppercase}
        .vl-live-route-metrics strong{display:block;overflow:hidden;margin-top:4px;color:var(--heading);font-size:var(--vl-body-size);font-weight:700;line-height:1.2;letter-spacing:-.25px;text-overflow:ellipsis;white-space:nowrap}
        .vl-live-route-unavailable{color:var(--status)!important;font-size:var(--vl-subtext-size)!important;font-weight:600!important}
        .vl-live-route-check{align-self:flex-start;min-height:var(--tap-min);padding:0 16px;border:0;border-radius:var(--pill-r);background:var(--lime);color:var(--green);font-size:var(--vl-control-size);font-weight:var(--vl-control-weight)}
        .vl-live-route-check:disabled{cursor:not-allowed;opacity:.45}

        /* ── FLOATING AIR QUALITY CARD ───────────────────────────────────────────────
           A white, rounded, home-system card floating over the full-bleed map's top-left corner,
           inset so it clears Google's bottom-left logo and bottom-right legal notices.
           Scrollable so a long pollutant list never spills past the map. NO red. */
        .vl-live-air-card-wrap{position:relative;z-index:12;grid-area:1/1;align-self:start;justify-self:start;width:min(416px,calc(100% - 32px));margin-block:16px 112px;margin-inline:16px 0;filter:none}
        .vl-live-mobile-snapshot{display:none}
        .vl-live-air-card{position:relative;width:100%;overflow:visible;padding:24px;border:1px solid var(--hair);border-radius:var(--panel-r);background:#fff;box-shadow:none;color:var(--body)}

        .vl-live-air-context{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 18px;padding:0 0 16px;border-bottom:1px solid var(--hair)}
        .vl-live-air-context-item{display:inline-flex;min-width:0;align-items:center;gap:9px;color:var(--status);font-size:var(--vl-subtext-size);line-height:1.35}
        .vl-live-air-context-item svg{flex:0 0 var(--vl-action-size);width:var(--vl-action-size);height:var(--vl-action-size);padding:7px;border-radius:50%;background:var(--lime);fill:var(--green)}
        .vl-live-air-context-item strong{min-width:0;overflow:hidden;color:var(--heading);font-size:var(--vl-data-size);font-weight:600;line-height:1.25;text-overflow:ellipsis;white-space:nowrap}
        .vl-live-air-context-item.is-time{justify-content:flex-end;white-space:nowrap}
        .vl-live-local-datetime{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
        .vl-live-air-context-item time{color:var(--heading);font-weight:600}
        .vl-live-air-context-item small{color:var(--muted);font-size:var(--vl-meta-size);font-weight:600}

        /* Air/Weather toggle - same pale tint + saturated same-hue dot as the hero pill. */
        .vl-live-air-toggle{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:4px;border:1px solid var(--hair);border-radius:var(--pill-r);background:#fff;box-shadow:0 6px 18px rgba(26,58,42,.08)}
        .vl-live-air-toggle-btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:var(--tap-min);border:0;border-radius:var(--pill-r);background:transparent;color:var(--green);font-size:var(--vl-subtext-size);font-weight:700;line-height:1;letter-spacing:0}
        .vl-live-air-toggle-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:rgba(26,58,42,.3)}
        .vl-live-air-toggle-btn:hover:not(.is-active){background:var(--vl-hover-bg);color:var(--green);box-shadow:var(--vl-hover-shadow)}
        .vl-live-air-toggle-btn.is-active{background:var(--lime);color:var(--green)}
        .vl-live-air-toggle-btn.is-active .vl-live-air-toggle-dot{background:var(--green)}

        .vl-live-air-panel{margin-top:16px}
        .vl-live-air-empty{margin:0;padding:14px 0;color:var(--muted);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.4}
        .vl-live-air-gauge-label{margin:0 0 10px;color:var(--green);font-size:var(--vl-meta-size);font-weight:700;letter-spacing:.08em;text-transform:uppercase}
        .vl-live-air-gauge-row{display:grid;grid-template-columns:4px auto minmax(0,1fr);align-items:center;gap:14px}
        /* HOME-PAGE HUE SPINE, not an AQI severity encoding. These are the exact three
           accent bars used by .home-flow-list: green / blue / purple. The AQI number +
           category text carry the meaning, so the decorative hue never has to be decoded. */
        .vl-live-air-aqi-spine{display:block;width:4px;height:64px;border-radius:999px;background:var(--lime)}
        .vl-live-air-aqi-score{display:flex;min-width:56px;flex-direction:column;align-items:flex-start;justify-content:center}
        .vl-live-air-aqi-number{display:block;color:var(--heading);font-size:var(--vl-metric-size);font-weight:var(--public-section-weight);line-height:1;letter-spacing:var(--public-section-tracking)}
        .vl-live-air-aqi-unit{display:block;margin-top:4px;color:var(--muted);font-size:var(--vl-meta-size);font-weight:700;line-height:1;letter-spacing:.08em;text-transform:uppercase}
        .vl-live-air-gauge-meta{min-width:0}
        .vl-live-air-gauge-word{display:block;color:var(--heading);font-size:var(--vl-panel-heading-size);font-weight:var(--vl-panel-heading-weight);line-height:var(--vl-panel-heading-lh);letter-spacing:var(--vl-panel-heading-track)}
        .vl-live-air-summary-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin-top:8px;color:var(--muted);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.35}
        .vl-live-air-summary-meta strong{color:var(--status);font-weight:700}
        .vl-live-air-summary-chip{display:inline-flex;align-items:center;gap:5px}
        .vl-live-air-summary-icon{flex:0 0 16px;width:16px;height:16px;padding:2px;border-radius:50%;background:var(--lime);fill:var(--green)}
        .vl-live-freshness{display:inline-flex;align-items:center;gap:6px;width:fit-content;padding:5px 9px;border:1px solid var(--lime);border-radius:var(--pill-r);background:var(--lime-tint);color:var(--green);font-size:var(--vl-meta-size);font-weight:700;line-height:1.25;white-space:nowrap}
        .vl-live-freshness-icon{flex:0 0 15px;width:15px;height:15px;fill:currentColor}
        .vl-live-data-age.is-stale,.vl-live-mobile-copy .vl-live-freshness.is-stale,.vl-live-wx-freshness.is-stale{background:var(--lime-tint);color:var(--green)}
        .vl-live-local-time-status{color:var(--muted);font-weight:600}

        .vl-live-air-pollutants,.vl-live-air-heatmap,.vl-live-air-forecast,.vl-live-air-health,.vl-live-air-history{margin-top:var(--vl-section-gap);padding-top:var(--vl-section-pad);border-top:1px solid var(--hair)}
        .vl-live-air-pollutants-title,.vl-live-air-heatmap-label,.vl-live-air-forecast-title,.vl-live-air-health-title,.vl-live-air-history-title{display:block;margin:0;color:var(--heading);font-size:var(--vl-panel-heading-size);font-weight:var(--vl-panel-heading-weight);line-height:var(--vl-panel-heading-lh);letter-spacing:var(--vl-panel-heading-track);padding-inline-start:10px;border-inline-start:3px solid var(--lime)}
        .vl-live-air-pollutants-title{margin-bottom:var(--vl-heading-gap)}
        /* overflow:visible (was hidden) so the side popover below can escape the list box
           and float beside its row without being clipped. The list keeps its rounded 12px
           frame; the first/last rows round their own outer corners so the row fills still
           follow the frame now that the list no longer clips them. No scrollbar colour and
           no scrollbar hider are introduced here (the card keeps only scrollbar-width:thin). */
        .vl-live-air-pollutant-list{margin:0;padding:0;list-style:none;border:1px solid var(--hair);border-radius:var(--radius-lg,12px);overflow:visible}
        .vl-live-air-pollutant-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(118px,auto) var(--vl-action-size);align-items:center;gap:var(--vl-content-gap);padding:14px 14px;background:#fff;border-inline-start:2px solid transparent;transition:background .15s ease,border-color .15s ease}
        .vl-live-air-pollutant-row:first-child{border-top-left-radius:11px;border-top-right-radius:11px}
        .vl-live-air-pollutant-row:last-child{border-bottom-left-radius:11px;border-bottom-right-radius:11px}
        .vl-live-air-pollutant-row+.vl-live-air-pollutant-row{border-top:1px solid var(--hair)}
        .vl-live-air-pollutant-value{justify-self:end;min-width:118px;color:var(--heading);font-size:var(--vl-data-size);font-weight:700;line-height:1.25;letter-spacing:-.2px;text-align:end;font-variant-numeric:tabular-nums}
        .vl-live-air-pollutant-value small{margin-inline-start:4px;color:var(--muted);font-size:var(--vl-meta-size);font-weight:600;letter-spacing:0}
        .vl-live-air-pollutant-label{min-width:0;color:var(--body);font-size:var(--vl-data-size);font-weight:700;line-height:1.25;letter-spacing:-.18px}
        /* ONE ACTION-ICON SYSTEM for the Air card. The remaining round icon actions
           share the same lime surface, green glyph and keyboard focus ring. */
        .vl-live-air-pollutant-info,
        .vl-live-air-heatmap-switch,
        .vl-live-air-pollutant-pop-close{display:inline-flex;align-items:center;justify-content:center;flex:0 0 var(--vl-action-size);width:var(--vl-action-size);height:var(--vl-action-size);padding:0;border:0;border-radius:50%;background:var(--lime);color:var(--green);box-shadow:none;transition:background-color .2s,transform .16s ease,box-shadow .16s ease;color-scheme:light}
        .vl-live-air-pollutant-info{cursor:help}
        .vl-live-air-pollutant-info:hover,
        .vl-live-air-heatmap-switch:hover:not(:disabled),
        .vl-live-air-pollutant-pop-close:hover{background:var(--lime);color:var(--green);border:0;box-shadow:var(--vl-hover-shadow);transform:translateY(-1px)}
        .vl-live-air-pollutant-info:focus-visible,
        .vl-live-air-heatmap-switch:focus-visible,
        .vl-live-air-pollutant-pop-close:focus-visible,
        .vl-live-air-health-tab:focus-visible,
        .vl-live-air-toggle-btn:focus-visible,
        .vl-live-air-range button:focus-visible,
        .vl-live-air-forecast-card:focus-visible,
        .vl-live-map-retry:focus-visible,
        .vl-live-air-history-chart:focus-visible{outline:3px solid var(--green);outline-offset:2px}
        .vl-live-air-pollutant-info svg,
        .vl-live-air-heatmap-switch svg,
        .vl-live-air-pollutant-pop-close svg{width:21px;height:21px;fill:currentColor}
        .vl-live-air-heatmap-switch:disabled{opacity:.4;cursor:not-allowed}

        /* Fixed sibling OUTSIDE the scrollable Air card: white home-page surface, compact copy,
           viewport-clamped position and an explicit close affordance. Lime is an accent only,
           never the popup background. The directional notch is shape-only reference language. */
        .vl-live-air-pollutant-tip{position:absolute;z-index:2200;width:min(360px,calc(100vw - 20px));max-height:min(320px,calc(100dvh - 20px));overflow:auto;overscroll-behavior:contain;padding:14px;border:1px solid var(--lime);border-top:3px solid var(--lime);border-radius:var(--panel-r);background:var(--vl-surface);color:var(--body);box-shadow:0 18px 42px rgba(16,24,20,.16);font-family:var(--font-sans);font-size:var(--vl-meta-size);font-weight:400;line-height:1.45;text-align:start;scrollbar-width:thin}
        .vl-live-air-pollutant-tip::before{content:"";position:absolute;width:10px;height:10px;background:#fff}
        .vl-live-air-pollutant-tip.is-right::before{left:-6px;top:24px;transform:rotate(45deg);border-left:1px solid var(--hair);border-bottom:1px solid var(--hair)}
        .vl-live-air-pollutant-tip.is-left::before{right:-6px;top:24px;transform:rotate(45deg);border-top:1px solid var(--hair);border-right:1px solid var(--hair)}
        .vl-live-air-pollutant-tip.is-bottom::before{top:-6px;left:50%;transform:translateX(-50%) rotate(45deg);border-left:1px solid var(--hair);border-top:1px solid var(--hair)}
        .vl-live-air-pollutant-tip.is-top::before{bottom:-6px;left:50%;transform:translateX(-50%) rotate(45deg);border-right:1px solid var(--hair);border-bottom:1px solid var(--hair)}
        .vl-live-air-pollutant-pop{display:flex;flex-direction:column;gap:14px}
        .vl-live-air-pollutant-pop-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
        .vl-live-air-pollutant-pop-title{display:inline-flex;min-height:32px;align-items:center;padding:0 12px;border:1px solid var(--lime);border-radius:var(--pill-r);background:var(--lime);color:var(--green);font-size:var(--vl-data-size);font-weight:700;line-height:1.2;letter-spacing:0}
        .vl-live-air-pollutant-pop-fullname{display:block;max-width:260px;margin-top:7px;color:var(--heading);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.4;overflow-wrap:anywhere}
        .vl-live-air-pollutant-pop-line{display:grid;grid-template-columns:78px minmax(0,1fr);gap:12px;align-items:start;padding-top:2px}
        .vl-live-air-pollutant-pop-line strong{font-size:var(--vl-meta-size);font-weight:700;letter-spacing:0}
        .vl-live-air-pollutant-pop-line span{min-width:0;color:var(--muted);font-size:var(--vl-meta-size);font-weight:400;line-height:1.45;overflow-wrap:anywhere}
        .vl-live-air-pollutant-pop-line.is-source strong{color:var(--green)}
        .vl-live-air-pollutant-pop-line.is-effect strong{color:var(--green)}
        .vl-live-air-pollutant-pop-text{color:var(--status);font-size:var(--vl-meta-size);line-height:1.4}
        .vl-live-air-pollutant-row:focus-within,.vl-live-air-pollutant-row:hover{background:rgba(209,244,112,.18);border-inline-start-color:var(--lime)}

        /* ── HEATMAP ──────────────────────────────────────────────────────────────
           One compact Material Symbols control; the separate Storm switch is intentionally gone. */
        .vl-live-air-heatmap-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:var(--vl-heading-gap)}
        .vl-live-air-heatmap-control{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}
        .vl-live-air-heatmap-state{color:var(--muted);font-size:var(--vl-meta-size);font-weight:700;line-height:1}
        .vl-live-air-heatmap-switch.is-on{background:var(--vl-active-bg);color:var(--green)}
        .vl-live-air-heatmap-legend{margin-top:0}
        .vl-live-air-heatmap-ramp{display:block;height:8px;border-radius:999px;background:linear-gradient(90deg,#c98a2e 0%,#e8c547 42%,#d1f470 74%,#3da35a 100%)}
        .vl-live-air-heatmap-legend.is-pm25 .vl-live-air-heatmap-ramp{background:linear-gradient(90deg,#9849e8 0%,#2563eb 100%)}
        .vl-live-air-heatmap-ends{display:flex;align-items:center;justify-content:space-between;margin-top:6px}
        .vl-live-air-heatmap-end{color:var(--muted);font-size:var(--vl-meta-size);font-weight:700;letter-spacing:.02em}
        .vl-live-air-range{display:inline-flex;align-items:center;gap:6px;padding:0;border-radius:var(--pill-r);background:transparent}
        /* The 44px tap floor (--tap-min) on the AQI/PM2.5 switch, the forecast scroll arrows and
           the health-profile pager - at every width, because the steering file's 44x44 applies to
           mouse and pen as well as touch, and tools/browser/devicecheck.js asserts it on VayuLok's
           live app at all 21 postures. These were 32px (measured on the live page, 2026-10-25). */
        .vl-live-air-range button{min-height:var(--tap-min);padding:0 10px;border:1px solid var(--hair);border-radius:var(--pill-r);background:#fff;color:var(--green);font-size:var(--vl-meta-size);font-weight:700;line-height:1;white-space:nowrap}
        .vl-live-air-range button.is-active{border-color:var(--lime);background:var(--lime);color:var(--green)}
        .vl-live-air-range button:hover{border-color:var(--lime);background:var(--vl-hover-bg);color:var(--green)}
        .vl-live-air-forecast-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:var(--vl-heading-gap);flex-wrap:wrap}
        .vl-live-air-forecast-head-actions{display:flex;min-width:0;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}
        .vl-live-air-scroll-nav{display:inline-flex;align-items:center;gap:4px}
        .vl-live-air-scroll-btn{display:inline-flex;width:var(--tap-min);height:var(--tap-min);align-items:center;justify-content:center;padding:0;border:1px solid var(--hair);border-radius:var(--pill-r);background:#fff;color:var(--green)}
        .vl-live-air-scroll-btn:hover{border-color:var(--lime);background:var(--vl-hover-bg);box-shadow:var(--vl-hover-shadow)}
        .vl-live-air-scroll-btn svg{width:16px;height:16px;fill:currentColor}
        .vl-live-air-forecast-strip{display:flex;gap:8px;overflow-x:auto;padding:0 0 8px;scroll-snap-type:x proximity;scrollbar-width:thin;overscroll-behavior-x:contain;touch-action:pan-x;-webkit-overflow-scrolling:touch}
        .vl-live-air-forecast-strip::-webkit-scrollbar{height:6px}
        .vl-live-air-forecast-card{display:flex;flex:0 0 clamp(142px,42vw,168px);width:clamp(142px,42vw,168px);min-width:142px;scroll-snap-align:start;flex-direction:column;align-items:flex-start;gap:4px;padding:10px 12px;border:1px solid var(--hair);border-radius:var(--radius-lg,12px);background:#fff;color:var(--body);text-align:start;touch-action:manipulation}
        .vl-live-air-forecast-card:hover{border-color:var(--lime);background:var(--vl-hover-bg)}
        .vl-live-air-forecast-card.is-active{border-color:var(--lime);background:var(--lime);color:var(--green)}
        .vl-live-air-forecast-card.is-active span,.vl-live-air-forecast-card.is-active strong,.vl-live-air-forecast-card.is-active small{color:var(--green)}
        .vl-live-air-forecast-card.is-skeleton{min-height:62px;background:linear-gradient(90deg,rgba(209,244,112,.12) 25%,rgba(209,244,112,.32) 37%,rgba(209,244,112,.12) 63%);background-size:400% 100%;border-color:var(--hair);animation:vl-live-shimmer 1.4s ease infinite}
        @media(prefers-reduced-motion:reduce){.vl-live-mobile-mode-indicator{transition:none}.vl-live-air-forecast-card.is-skeleton{animation:none}}
        @keyframes vl-live-shimmer{0%{background-position:100% 0}100%{background-position:-100% 0}}
        .vl-live-air-forecast-card span{color:var(--muted);font-size:var(--vl-meta-size);font-weight:600;line-height:1.4;white-space:normal}
        .vl-live-air-forecast-card strong{color:var(--heading);font-size:var(--vl-data-size);font-weight:700;line-height:1.35;letter-spacing:-.18px}
        .vl-live-air-forecast-card small{color:var(--status);font-size:var(--vl-meta-size);font-weight:600;line-height:1.4}
        .vl-live-air-forecast-detail{display:flex;flex-wrap:nowrap;gap:8px;margin-top:10px;padding:2px 0 8px;overflow-x:auto;scroll-snap-type:x proximity;scrollbar-width:thin;overscroll-behavior-x:contain;touch-action:pan-x;-webkit-overflow-scrolling:touch;color:var(--muted);font-size:var(--vl-meta-size);font-weight:400;line-height:1.4}
        .vl-live-air-forecast-detail>span{display:inline-flex;flex:0 0 auto;min-height:36px;align-items:center;gap:4px;padding:0 11px;border:1px solid rgba(209,244,112,.72);border-radius:var(--pill-r);background:var(--lime-tint);white-space:nowrap;scroll-snap-align:start}
        .vl-live-air-forecast-detail strong{color:var(--green);font-weight:600}
        .vl-live-air-history-detail::-webkit-scrollbar{height:6px}
        .vl-live-air-history-detail>.vl-live-air-history-pollutant{display:inline-flex}

        /* ── WEATHER TAB ─────────────────────────────────────────────────────────
           Reuses the Air panel's section headings, range pills and forecast strip/detail; these
           rules add only the pieces specific to Weather (the current hero, the metric grid, the
           10-day rows, the history strip, the alerts block). Same tokens, no red. */
        .vl-live-wx-now{display:grid;grid-template-columns:4px auto minmax(0,1fr);align-items:center;gap:14px;margin-bottom:var(--vl-section-gap)}
        .vl-live-wx-now-head{display:contents}
        .vl-live-wx-now-icon{grid-column:2;width:52px;height:52px;object-fit:contain}
        .vl-live-wx-now-temp{display:block;color:var(--heading);font-size:var(--vl-metric-size);font-weight:var(--public-section-weight);line-height:1;letter-spacing:var(--public-section-tracking)}
        .vl-live-wx-now-cond{display:block;margin-top:2px;color:var(--heading);font-size:var(--vl-panel-heading-size);font-weight:var(--vl-panel-heading-weight);line-height:var(--vl-panel-heading-lh);letter-spacing:var(--vl-panel-heading-track)}
        .vl-live-wx-now-sub{grid-column:3;display:flex;flex-wrap:wrap;gap:6px 10px;color:var(--muted);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.35}
        .vl-live-wx-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;margin:0 0 var(--vl-section-gap);padding:0;list-style:none;border:1px solid var(--hair);border-radius:var(--radius-lg,12px);overflow:hidden;background:var(--hair)}
        .vl-live-wx-grid-item{display:flex;align-items:baseline;justify-content:space-between;gap:var(--vl-content-gap);padding:14px;background:#fff;transition:background-color .14s ease}
        .vl-live-wx-grid-k{min-width:0;color:var(--body);font-size:var(--vl-data-size);font-weight:700;line-height:1.35;letter-spacing:-.18px}
        .vl-live-wx-grid-v{color:var(--muted);font-size:var(--vl-data-size);font-weight:600;line-height:1.35;letter-spacing:-.1px;font-variant-numeric:tabular-nums;text-align:end}
        .vl-live-wx-grid-item:last-child:nth-child(odd){grid-column:1/-1}
        .vl-live-wx-daily{margin-top:var(--vl-section-gap)}
        .vl-live-wx-daily-list{max-height:430px;margin:var(--vl-heading-gap) 0 0;padding:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;list-style:none}
        .vl-live-wx-daily-row{display:grid;grid-template-columns:68px 30px minmax(0,1fr) auto auto;align-items:center;gap:10px;width:100%;min-height:48px;padding:12px 14px;border:0;border-top:1px solid var(--hair);border-inline-start:2px solid transparent;border-radius:0;background:#fff;color:var(--body);text-align:start;cursor:pointer;transition:background-color .14s ease,border-color .14s ease}
        .vl-live-wx-daily-list li:first-child .vl-live-wx-daily-row{border-top:0}
        .vl-live-wx-daily-row:hover{background:var(--vl-hover-bg);border-inline-start-color:var(--lime)}
        .vl-live-wx-daily-row.is-active{background:var(--vl-active-bg);border-inline-start-color:var(--lime);color:var(--green)}
        .vl-live-wx-daily-day{color:var(--body);font-size:var(--vl-data-size);font-weight:700;line-height:1.35;letter-spacing:-.18px}
        .vl-live-wx-daily-icon,.vl-live-wx-daily-icon-spacer{display:block;width:28px;height:28px;object-fit:contain}
        .vl-live-wx-daily-cond{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:var(--vl-compact-copy-size);font-weight:600;line-height:1.4}
        .vl-live-wx-daily-temp{color:var(--heading);font-size:var(--vl-data-size);font-weight:700;line-height:1.35;letter-spacing:-.2px;font-variant-numeric:tabular-nums}
        .vl-live-wx-daily-rain{color:var(--status);font-size:var(--vl-meta-size);font-weight:600;line-height:1.4}
        .vl-live-wx-history{margin-top:var(--vl-section-gap)}
        .vl-live-wx-history .vl-live-air-forecast-head{display:block;margin-bottom:8px}
        .vl-live-wx-history .vl-live-air-forecast-title{white-space:nowrap}
        .vl-live-wx-history .vl-live-air-range{
          display:flex;gap:6px;width:100%;max-width:100%;margin-top:8px;padding:0;
          overflow-x:auto;overflow-y:hidden;scroll-snap-type:x proximity;scrollbar-width:thin;
          -webkit-overflow-scrolling:touch;overscroll-behavior-inline:contain;
          touch-action:pan-x;border-radius:var(--pill-r);background:transparent;
        }
        .vl-live-wx-history .vl-live-air-range::-webkit-scrollbar{height:6px}
        .vl-live-wx-history .vl-live-air-range button{
          position:relative;flex:0 0 auto;min-width:max-content;min-height:var(--tap-min);
          padding:0 10px;scroll-snap-align:center;border:1px solid var(--hair);border-radius:var(--pill-r);background:#fff;
          color:var(--green);font-size:var(--vl-meta-size);font-weight:700;white-space:nowrap;
        }
        .vl-live-wx-history .vl-live-air-range button:hover{border-color:var(--lime);background:var(--vl-hover-bg);color:var(--green)}
        .vl-live-wx-history .vl-live-air-range button.is-active{border-color:var(--lime);background:var(--lime);color:var(--green)}
        .vl-live-wx-hist-strip{display:flex;gap:8px;margin:8px 0 0;padding:0 0 8px;overflow-x:auto;list-style:none;scrollbar-width:thin;overscroll-behavior-x:contain;touch-action:pan-x}
        .vl-live-wx-hist-strip::-webkit-scrollbar{height:6px}
        .vl-live-wx-hist-slot{flex:0 0 clamp(142px,42vw,168px)}
        .vl-live-wx-hist-item{display:flex;width:100%;min-height:86px;flex-direction:column;align-items:flex-start;justify-content:center;gap:4px;padding:10px 12px;border:1px solid var(--hair);border-radius:var(--radius-lg,12px);background:#fff;text-align:start}
        .vl-live-wx-hist-item:hover{border-color:var(--lime);background:var(--vl-hover-bg)}
        .vl-live-wx-hist-item.is-active{border-color:var(--lime);background:var(--lime);color:var(--green)}
        .vl-live-wx-hist-item.is-active .vl-live-wx-hist-t,.vl-live-wx-hist-item.is-active .vl-live-wx-hist-v{color:var(--green)}
        .vl-live-wx-hist-t{color:var(--muted);font-size:var(--vl-meta-size);font-weight:600;line-height:1.4;white-space:nowrap}
        .vl-live-wx-hist-v{color:var(--heading);font-size:var(--vl-data-size);font-weight:700;line-height:1.35;letter-spacing:-.2px;font-variant-numeric:tabular-nums}
        .vl-live-wx-alerts{margin-top:var(--vl-section-gap)}
        .vl-live-wx-alert{display:flex;flex-direction:column;gap:3px;margin-top:var(--vl-heading-gap);padding:12px 14px;border:1px solid var(--hair);border-inline-start:3px solid var(--lime);border-radius:var(--radius-lg,12px);background:#fff}
        .vl-live-wx-alert.sev-extreme,.vl-live-wx-alert.sev-severe{border-inline-start-color:#c98a2e;background:var(--lime-tint)}
        .vl-live-wx-alert.sev-moderate{border-inline-start-color:#e8c547}
        .vl-live-wx-alert strong{color:var(--heading);font-size:var(--vl-data-size);font-weight:700;line-height:1.35;letter-spacing:-.18px}
        .vl-live-wx-alert-meta{color:var(--status);font-size:var(--vl-meta-size);font-weight:700;line-height:1.4;letter-spacing:.02em;text-transform:uppercase}
        .vl-live-wx-alert-area{color:var(--muted);font-size:var(--vl-compact-copy-size);font-weight:600;line-height:1.4}
        .vl-live-wx-alert p{margin:2px 0 0;color:var(--body);font-size:var(--vl-compact-copy-size);font-weight:400;line-height:1.5}
        .vl-live-wx-alert-src{color:var(--muted);font-size:var(--vl-meta-size);font-weight:600;line-height:1.4}
        .vl-live-wx-alert-event,.vl-live-wx-alert-time{color:var(--muted);font-size:var(--vl-meta-size);font-weight:600;line-height:1.4}
        .vl-live-wx-alert-src a{color:var(--green);font-weight:700;text-decoration:underline;text-underline-offset:2px}
        .vl-live-wx-alert-map-btn{align-self:flex-start;min-height:var(--tap-min);margin-top:6px;padding:7px 12px;border:1px solid var(--green);border-radius:var(--pill-r);background:#fff;color:var(--green);font:inherit;font-size:var(--vl-control-size);font-weight:var(--vl-control-weight);cursor:pointer}
        .vl-live-wx-alert-map-btn:hover,.vl-live-wx-alert-map-btn[aria-pressed="true"]{background:var(--lime-tint)}
        .vl-live-wx-daily-expand{padding:10px 14px 14px;border-top:1px solid var(--hair);background:#fff}
        .vl-live-wx-period-toggle{width:max-content;margin:0 0 10px}
        .vl-live-wx-period-summary{display:flex;align-items:center;gap:8px;margin-bottom:8px}
        .vl-live-wx-period-summary img{width:34px;height:34px;object-fit:contain}
        .vl-live-wx-hour-icon{width:28px;height:28px;object-fit:contain}
        .vl-live-wx-period-summary strong{font-size:var(--vl-data-size);font-weight:700;line-height:1.35}
        .vl-live-wx-freshness{margin-top:8px}

        /* ── HEALTH RECOMMENDATIONS ──────────────────────────────────────────────
           Profiles are one touch/keyboard scroll rail using the same small pill language as
           VayuLok's other selectors. Advisory copy stays regular and muted so it does not compete with live data. */
        .vl-live-air-history-pollutant{display:inline-flex;align-items:center;gap:4px}
        .vl-live-air-health-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:var(--vl-heading-gap)}
        .vl-live-air-health-head-nav{display:inline-flex;align-items:center;gap:6px;flex:0 0 auto}
        .vl-live-air-health-rail-shell{display:block}
        .vl-live-air-health-page{display:inline-flex;width:var(--tap-min);height:var(--tap-min);align-items:center;justify-content:center;padding:0;border:1px solid var(--lime);border-radius:50%;background:var(--lime-tint);color:var(--green)}
        .vl-live-air-health-page:hover:not(:disabled){border-color:var(--lime);background:var(--vl-hover-bg);box-shadow:var(--vl-hover-shadow)}
        .vl-live-air-health-page:disabled{opacity:.42;cursor:default}
        .vl-live-air-health-page svg{width:18px;height:18px;fill:currentColor}
        .vl-live-air-health-tabs{display:flex;align-items:center;gap:8px;overflow-x:auto;padding:0 0 8px;scroll-snap-type:x proximity;scrollbar-width:thin;white-space:nowrap;overscroll-behavior-x:contain;touch-action:pan-x}
        .vl-live-air-health-tabs::-webkit-scrollbar{height:6px}
        .vl-live-air-health-tab{display:inline-flex;flex:0 0 48px;width:48px;height:48px;min-height:48px;align-items:center;justify-content:center;padding:0;border:1px solid var(--lime);border-radius:50%;background:var(--lime-tint);color:var(--green);line-height:1;scroll-snap-align:start;transition:background-color .2s,border-color .2s}
        .vl-live-air-health-tab:hover{border-color:var(--lime);background:var(--vl-hover-bg);color:var(--green);box-shadow:var(--vl-hover-shadow)}
        .vl-live-air-health-tab.is-active{border-color:var(--lime);background:var(--lime);color:var(--green);box-shadow:none}
        .vl-live-air-health-icon-wrap{display:flex;align-items:center;justify-content:center;flex:0 0 24px;width:24px;height:24px;border:0;border-radius:inherit;background:transparent;color:inherit}
        .vl-live-air-health-icon{width:24px;height:24px;fill:currentColor}
        .vl-live-air-health-tooltip{position:absolute;z-index:4;inset-inline-start:50%;bottom:calc(100% + 7px);max-width:180px;transform:translateX(-50%) translateY(3px);padding:5px 8px;border:1px solid var(--lime);border-radius:var(--radius-md,10px);background:var(--vl-surface);color:var(--green);font-size:var(--vl-meta-size);font-weight:600;line-height:1.3;white-space:normal;opacity:0;pointer-events:none;transition:opacity .14s ease,transform .14s ease}
        .vl-live-air-health-tab{position:relative}
        :global(.vl-ui-icon-action:hover) .vl-live-air-health-tooltip,:global(.vl-ui-icon-action:focus-visible) .vl-live-air-health-tooltip{opacity:1;transform:translateX(-50%) translateY(0)}
        .vl-live-air-health-panel{margin-top:var(--vl-content-gap);padding-top:var(--vl-content-gap);border-top:1px solid var(--hair)}
        .vl-live-air-health-persona{display:block;margin:0 0 6px;color:var(--heading);font-size:var(--vl-data-size);font-weight:600;line-height:1.35;letter-spacing:-.1px}
        .vl-live-air-health-text{margin:0;color:var(--muted);font-size:var(--vl-subtext-size);font-weight:400;line-height:1.5;letter-spacing:0}

        /* ── HOURLY HISTORY (inline-SVG AQI chart) ──────────────────────────────────
           Line + area stroked from the no-red ramp via the sev-mapped class; the pinned
           bubble shows the current AQI number so meaning never rests on colour alone. */
        .vl-live-air-history-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:var(--vl-heading-gap)}
        .vl-live-air-history-head-meta{display:flex;align-items:center;gap:8px}
        .vl-live-air-history-stamp{display:flex;width:fit-content;align-items:center;gap:6px;margin:10px auto 0;padding:6px 12px;border-radius:var(--pill-r);background:var(--lime-tint);color:var(--green);font-size:var(--vl-meta-size);font-weight:700;line-height:1.4;letter-spacing:0;white-space:nowrap}
        .vl-live-air-history-stamp-icon{flex:0 0 15px;width:15px;height:15px;fill:var(--green)}
        .vl-live-air-history-empty{margin:0;color:var(--muted);font-size:var(--vl-subtext-size);font-weight:600;line-height:1.4}
        .vl-live-air-history-chart{position:relative;margin-top:0;touch-action:pan-y;cursor:crosshair}
        .vl-live-air-history-svg{display:block;width:100%;height:120px}
        .vl-live-air-history-grid{stroke:var(--hair);stroke-width:1;stroke-dasharray:2 3}
        .vl-live-air-history-day{fill:var(--muted);font-size:var(--vl-meta-size);font-weight:600}
        .vl-live-air-history-leader{stroke:var(--muted);stroke-width:1;stroke-dasharray:2 2}
        .vl-live-air-history-line{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
        .vl-live-air-history-area{fill:currentColor;opacity:.12;stroke:none}
        .vl-live-air-history-dot{stroke:#fff;stroke-width:2}
        .vl-live-air-history-inspect-line{stroke:rgba(26,58,42,.42);stroke-width:1;stroke-dasharray:2 2}
        .vl-live-air-history-inspect-dot{fill:var(--lime);stroke:var(--green);stroke-width:2}
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

        /* ROUNDED MAP SECTION. The whole map area now carries the same corner radius as the
           surrounding cards (var(--panel-r) = the shared --radius-xl), so it no longer reads as a
           square against the rounded floating card. The SHELL keeps overflow:visible so the
           floating .vl-live-air-card is never clipped; instead the radius is applied to the map's
           VISUAL layers that fill it (canvas, placeholder, fallback, atmosphere), each with
           overflow:hidden, so the Google tiles/overlays and loading/fallback states clip to the
           rounded corners. isolation:isolate keeps the overlay z-stack contained; the height band
           is unchanged. */
        .vl-live-map-shell{position:relative;display:grid;height:auto;min-height:min(620px,72svh);max-height:none;overflow:visible;border-radius:var(--panel-r);background:var(--lime-tint);isolation:isolate;contain:layout}
        .vl-live-map-canvas,.vl-live-map-placeholder{position:absolute;inset:0;width:100%;height:100%;border-radius:var(--panel-r);overflow:hidden}
        .vl-live-map-canvas{opacity:0}
        .vl-live-map-canvas.is-ready{opacity:1}
        .vl-live-weather-visual{position:absolute;inset:0;z-index:5;overflow:hidden;border-radius:var(--panel-r);pointer-events:none}
        .vl-live-sky-wash{position:absolute;inset:0;opacity:var(--vl-sky-opacity)}
        .vl-live-weather-visual.is-day .vl-live-sky-wash{background:linear-gradient(180deg,rgba(93,173,226,.64),rgba(187,224,247,.34) 58%,rgba(255,255,255,.06))}
        .vl-live-weather-visual.is-night .vl-live-sky-wash{background:linear-gradient(180deg,rgba(17,32,61,.75),rgba(45,66,96,.46) 60%,rgba(255,255,255,.04))}
        .vl-live-weather-visual.is-cloudy .vl-live-sky-wash{background:linear-gradient(180deg,rgba(116,139,158,.58),rgba(205,216,222,.32) 62%,rgba(255,255,255,.08))}
        .vl-live-weather-visual.is-rainy .vl-live-sky-wash{background:linear-gradient(180deg,rgba(75,99,124,.66),rgba(150,170,184,.36) 62%,rgba(219,234,242,.10))}
        .vl-live-cloud-field{position:absolute;inset:-8%;opacity:var(--vl-cloud-opacity);filter:blur(11px);animation:vl-live-cloud-drift 22s ease-in-out infinite alternate}
        .vl-live-cloud-field i{position:absolute;display:block;border-radius:50%;background:radial-gradient(ellipse at center,rgba(255,255,255,.80),rgba(244,248,250,.50) 48%,rgba(224,232,236,0) 74%)}
        .vl-live-cloud-field i:nth-child(1){width:42%;height:28%;left:-4%;top:8%}.vl-live-cloud-field i:nth-child(2){width:48%;height:32%;right:-8%;top:18%}
        .vl-live-cloud-field i:nth-child(3){width:38%;height:26%;left:24%;top:44%}.vl-live-cloud-field i:nth-child(4){width:44%;height:30%;right:4%;bottom:0}
        @keyframes vl-live-cloud-drift{from{transform:translate3d(-2%,0,0)}to{transform:translate3d(3%,1.5%,0)}}
        /* Narrow live test: hide only Google attribution/branding nodes; do not touch map controls. */
        .vl-live :global(.gm-style-cc),
        .vl-live :global(a[aria-label="Google Maps"]),
        .vl-live :global(img[alt="Google"]){display:none!important}
        .vl-live-map-placeholder{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding:24px;text-align:center;z-index:0;background:var(--lime-tint);color:var(--green)}
        .vl-live-map-placeholder strong{font-size:var(--vl-subtext-size);letter-spacing:0}
        .vl-live-map-placeholder span{font-size:var(--vl-meta-size);color:var(--muted)}
        .vl-live-map-placeholder p{margin:4px 0 0;font-size:var(--vl-meta-size);color:var(--status)}
        .vl-live-map-retry{margin-top:10px;min-height:var(--tap-min);padding:0 16px;border:0;border-radius:var(--pill-r);background:var(--lime);color:var(--green);font-size:var(--vl-control-size);font-weight:var(--vl-control-weight);cursor:pointer;transition:background-color .2s,transform .16s ease}
        .vl-live-map-retry:hover{background:var(--lime);box-shadow:var(--vl-hover-shadow);transform:translateY(-1px)}
        .vl-live-map-fallback{position:absolute;inset:0;display:grid;place-items:center;z-index:0;border-radius:var(--panel-r);background:var(--lime-tint);color:var(--green);font-size:var(--vl-subtext-size)}
        .vl-live-map-loading-dot{width:9px;height:9px;border-radius:50%;background:rgba(26,58,42,.28);animation:vl-live-map-pulse 1.15s ease-in-out infinite alternate}
        @keyframes vl-live-map-pulse{to{opacity:.35;transform:scale(.72)}}
        .vl-live-map-fallback button{min-height:var(--tap-min);margin-inline-start:8px;border:1px solid var(--green);border-radius:var(--pill-r);background:#fff;color:var(--green);padding:7px 11px}
        /* DESTINATION SEARCH is a separate page section ABOVE the map shell. Its outer
           wrapper is deliberately invisible: the only visible field chrome is the same
           bottom hairline used by Header .nav-search and ProductBlogPanel .pbp-search. */
        .vl-live-map-search{position:relative;z-index:30;width:min(760px,calc(100% - 48px));margin:14px auto 20px;padding:0;background:transparent;border:0;border-radius:0;box-shadow:none}
        .vl-live-search{position:relative}
        /* Exact Header.tsx .nav-search INPUT treatment, with one optional voice action floated
           inside the right edge. The mic does not change the hairline/search-box geometry. */
        .vl-live-search-field{position:relative;display:block;height:52px;padding:0;background:transparent;border-radius:0}
        .vl-live-search-field input{width:100%;height:52px;box-sizing:border-box;border:0;border-bottom:1px solid #e5e7eb;border-radius:0;background:transparent;padding-block:0;padding-inline:2px 44px;font-size:var(--vl-data-size);font-weight:400;line-height:1.3;color:rgba(0,0,0,.898);font-family:inherit;outline:none;transition:border-color .2s,box-shadow .2s}
        .vl-live-search-field input::placeholder{color:var(--public-muted)}
        .vl-live-search-field input::-webkit-search-cancel-button,.vl-live-search-field input::-webkit-search-decoration{display:none;-webkit-appearance:none}
        .vl-live-search-field input::-ms-clear{display:none;width:0;height:0}
        /* LIGHT, MINIMAL FOCUS. No heavy rectangular outline around the whole field - just a
           thin dark-green bottom border with a subtle lime accent line, matching the site's
           modern search treatment. Keyboard focus stays clearly visible. */
        .vl-live-search-field input:focus-visible{outline:none;border-bottom-color:#1a3a2a;box-shadow:0 1px 0 0 var(--lime)}
        .vl-live-search-results{position:absolute;top:calc(100% + 8px);inset-inline:0;z-index:31;margin:0;padding:6px;list-style:none;border:1px solid var(--hair);border-radius:var(--panel-r);background:#fff;box-shadow:none}
        /* RESULT ROWS: clear hover + keyboard-selected states with a soft lime background and a
           smooth 140ms transition. A small location glyph leads each row, matching the air card's
           icon idiom; no heavy shadow, no oversized card. */
        .vl-live-search-results li{display:flex;align-items:flex-start;gap:9px;padding:10px 12px;border-radius:var(--radius-md,10px);cursor:pointer;transition:background-color .14s ease}
        .vl-live-search-results li:hover,.vl-live-search-results li[aria-selected="true"]{background:var(--lime-tint)}
        .vl-live-search-results li[aria-selected="true"]{box-shadow:inset 2px 0 0 var(--lime)}
        .vl-live-search-result-icon{flex:0 0 16px;width:16px;height:16px;margin-top:2px;fill:var(--green);opacity:.72}
        .vl-live-search-result-text{min-width:0}
        .vl-live-search-results strong,.vl-live-search-results span{display:block}
        .vl-live-search-results strong{font-size:var(--vl-data-size);font-weight:700;color:var(--heading);letter-spacing:-.18px}
        .vl-live-search-results span{margin-top:3px;font-size:var(--vl-subtext-size);color:var(--muted)}
        .vl-live-search-status{margin:8px 2px 0;font-size:var(--vl-meta-size);color:var(--muted)}
        @media(max-width:1050px){
          .vl-live-map-shell{height:auto;min-height:min(560px,66svh)}
        }
        /* A browser that exposes physical viewport segments is telling us part of the viewport
           may be occluded by a hinge. Keep the live VayuLok application wholly inside one pane,
           matching the migrated hero. Physical margin-left/right is intentional here because
           viewport-segment-* itself describes physical screen geometry, not document direction. */
        @media(horizontal-viewport-segments:2){
          .vl-live-shell{
            width:env(viewport-segment-width 0 0);
            max-width:env(viewport-segment-width 0 0);
            margin-left:env(viewport-segment-left 0 0);
            margin-right:auto;
            box-sizing:border-box;
          }
          :global([dir='rtl']) .vl-live-shell{
            width:env(viewport-segment-width 1 0);
            max-width:env(viewport-segment-width 1 0);
            margin-left:env(viewport-segment-left 1 0);
            margin-right:0;
          }
        }
        @media(max-width:700px){
          .vl-live{--vl-card-heading-size:var(--public-mobile-card-size);--vl-metric-size:var(--public-mobile-section-size);--vl-meta-size:var(--public-meta-size);--vl-compact-copy-size:var(--vl-subtext-size)}

          .vl-live-shell{padding:0 max(var(--public-mobile-page-gutter),var(--safe-right)) max(var(--public-mobile-section-gap),var(--safe-bottom)) max(var(--public-mobile-page-gutter),var(--safe-left))}
          .vl-live-map-shell{display:block;height:auto;min-height:0;max-height:none;padding-top:360px;background:transparent;contain:layout}
          .vl-live-map-canvas,.vl-live-map-placeholder,.vl-live-map-fallback,.vl-live-weather-visual{inset:0 0 auto;height:360px}
          .vl-live-map-search{width:calc(100% - 20px);margin:10px auto 16px;padding:0}
          .vl-live-mobile-snapshot{
            display:block;position:absolute;z-index:13;inset-inline:20px;top:94px;
            padding:14px;border:1px solid var(--hair);border-radius:var(--panel-r);
            background:rgba(255,255,255,.96);backdrop-filter:blur(8px);
            box-shadow:0 8px 20px rgba(26,58,42,.08)
          }
          .vl-live-mobile-snapshot-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
          .vl-live-mobile-snapshot-head>span{display:flex;min-width:0;flex-direction:column;gap:2px}
          .vl-live-mobile-snapshot-head strong{overflow:hidden;color:var(--heading);font-size:var(--vl-data-size);font-weight:700;text-overflow:ellipsis;white-space:nowrap}
          .vl-live-mobile-snapshot-head small{color:var(--muted);font-size:var(--vl-meta-size);font-weight:600}
          /* Air / Weather is a segmented MODE control, not two unexplained icon buttons.
             Keep both labels visible so the state is immediately understandable without relying
             on icon recognition or hover tooltips. The outer rail stays neutral; colour belongs
             to the selected segment only. */
          .vl-live-mobile-mode{
            position:relative;display:grid;flex:0 0 auto;grid-template-columns:1fr 1fr;gap:3px;
            width:116px;padding:3px;border:1px solid var(--hair);border-radius:var(--pill-r);
            background:rgba(255,255,255,.96);box-shadow:0 1px 3px rgba(26,58,42,.08)
          }
          .vl-live-mobile-mode-indicator{
            position:absolute;z-index:0;inset-block:3px;inset-inline-start:3px;width:calc(50% - 5px);
            border:1px solid rgba(26,58,42,.32);border-radius:var(--pill-r);background:var(--lime);
            box-shadow:0 1px 4px rgba(26,58,42,.12);pointer-events:none;box-sizing:border-box;
            transform:translateX(0);
            transition:transform .22s cubic-bezier(.16,1,.3,1),background-color .18s ease,border-color .18s ease
          }
          .vl-live-mobile-mode.is-weather .vl-live-mobile-mode-indicator{
            transform:translateX(calc(100% + 4px));background:#e8f5ff;border-color:#b9d9e8
          }
          .vl-live-mobile-mode button{
            position:relative;z-index:1;display:grid;place-items:center;
            min-width:var(--tap-min);min-height:var(--tap-min);padding:0;border:0;border-radius:var(--pill-r);
            background:transparent;color:#728079;cursor:pointer
          }
          .vl-live-mobile-mode button:hover{background:rgba(26,58,42,.035)}
          .vl-live-mobile-mode .is-air[aria-pressed='true']{color:var(--green)}
          .vl-live-mobile-mode .is-weather[aria-pressed='true']{color:#416f84}
          .vl-live-mobile-mode button:focus-visible{outline:3px solid var(--green);outline-offset:2px}
          .vl-live-mode-icon{
            width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2;
            stroke-linecap:round;stroke-linejoin:round;pointer-events:none;
            transition:transform .18s ease
          }
          .vl-live-mobile-mode button[aria-pressed='true'] .vl-live-mode-icon{transform:scale(1.06)}
          @media(max-width:380px){
            .vl-live-mobile-mode{width:112px}
          }
          .vl-live-mobile-snapshot-body{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:14px;margin-top:12px;padding-top:12px;border-top:1px solid var(--hair)}
          .vl-live-mobile-primary{display:flex;min-width:74px;flex-direction:column}
          .vl-live-mobile-primary strong{color:var(--heading);font-size:var(--vl-metric-size);font-weight:var(--public-section-weight);line-height:1;letter-spacing:var(--public-section-tracking)}
          .vl-live-mobile-primary span{margin-top:4px;color:var(--muted);font-size:var(--vl-meta-size);font-weight:700}
          .vl-live-mobile-copy{display:flex;min-width:0;flex-direction:column;gap:3px;color:var(--body);font-size:var(--vl-subtext-size);line-height:1.4}
          .vl-live-mobile-copy>strong{color:var(--heading);font-size:var(--vl-data-size)}
          .vl-live-mobile-copy b{font-weight:750}
          .vl-live-mobile-copy small{margin-top:2px;color:var(--muted);font-size:var(--vl-meta-size)}
          .vl-live-mobile-empty{margin:12px 0 0;padding-top:12px;border-top:1px solid var(--hair);color:var(--muted);font-size:var(--vl-subtext-size)}
          /* Compact copy keeps the same Home/public role tokens on mobile; only the documented
             Home mobile card/metric rungs change above. There is no second phone-only type scale. */
          .vl-live-air-card-wrap{display:block;position:relative;z-index:12;width:100%;max-width:100%;min-width:0;margin:20px 0 56px;filter:none}
          .vl-live-air-card{width:100%;max-width:100%;min-width:0;padding:20px}
          .vl-live-air-panel{min-width:0;max-width:100%}
          .vl-live-air-gauge-row{
            position:relative;display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:auto auto;
            align-items:center;row-gap:8px;min-width:0;max-width:100%;padding-inline:16px
          }
          .vl-live-air-aqi-spine{
            position:absolute;inset-inline-start:0;top:50%;width:4px;height:92px;min-height:92px;
            transform:translateY(-50%)
          }
          .vl-live-air-aqi-score{
            grid-column:1;grid-row:1;justify-self:center;min-width:0;
            flex-direction:row;align-items:baseline;gap:8px
          }
          .vl-live-air-aqi-unit{margin-top:0}
          .vl-live-air-gauge-meta{
            grid-column:1;grid-row:2;justify-self:stretch;min-width:0;max-width:100%;text-align:center
          }
          .vl-live-air-gauge-word{max-width:100%;font-size:var(--vl-card-heading-size);white-space:normal;overflow-wrap:anywhere;word-break:normal;text-align:center}
          .vl-live-air-summary-meta{min-width:0;max-width:100%;justify-content:center;text-align:center}
          .vl-live-air-summary-chip{min-width:0;max-width:100%;white-space:normal}
          .vl-live-air-summary-chip>span{min-width:0;overflow-wrap:anywhere}
          .vl-live-air-context{align-items:flex-start}
          .vl-live-air-context-item.is-location{max-width:56%}
          .vl-live-air-context-item.is-time{margin-inline-start:auto}
          .vl-live-air-health-tabs{scroll-snap-type:x mandatory;overscroll-behavior-x:contain;scroll-padding-inline:2px}
          .vl-live-air-history-head,.vl-live-air-forecast-head{align-items:flex-start;flex-direction:column}
          .vl-live-wx-history .vl-live-air-forecast-head{display:block}
          /* MOBILE: STACK THE DAILY-FORECAST TABLE VERTICALLY. The desktop 5-column row
             (day / icon / condition / temp / rain) and the earlier 4-column phone fallback both
             squeezed the condition text (white-space:nowrap -> hard ellipsis) and felt cramped
             below ~400px. On a phone each day now reads top-to-bottom: a top line pairs the day
             label (with its icon) on the left against the temperature on the right, and the full
             condition text wraps underneath on its own line - and the rain% comes back (it was
             display:none only because there was no room in the squeezed 4-col layout). Named
             grid areas keep the DOM order (day, icon, cond, temp, rain) rendering as two readable
             lines without reordering the markup. The desktop base rule at ~4840 is untouched, so
             the test that pins its exact string still passes - this is a mobile-only override. */
          .vl-live-wx-daily-row{
            grid-template-columns:28px minmax(0,1fr) auto;
            grid-template-areas:'icon day temp' 'cond cond cond';
            align-items:center;row-gap:4px;column-gap:10px;padding:14px;min-height:0
          }
          .vl-live-wx-daily-icon,.vl-live-wx-daily-icon-spacer{grid-area:icon}
          .vl-live-wx-daily-day{grid-area:day}
          .vl-live-wx-daily-temp{grid-area:temp;justify-self:end}
          /* The condition sits full-width on the second line and WRAPS instead of truncating. */
          .vl-live-wx-daily-cond{grid-area:cond;white-space:normal;overflow:visible;text-overflow:clip}
          /* Rain% rides the end of the condition line, so clear the display:none fallback. */
          .vl-live-wx-daily-rain{grid-area:cond;justify-self:end;display:block}
          /* MOBILE: STACK THE AIR POLLUTANT TABLE. The desktop 3-column row
             (label / value>=118px / 36px info button) had no phone rule, so on a 320-430px screen
             the label was squeezed against a 118px value reservation. Stack it: the pollutant
             name on its own line, then the value (left-aligned now) and the info button paired on
             the line below. Base rule + the value's min-width/right-align/tabular-nums pins at
             ~4707/4712 stay as-is for desktop; these only apply under 700px. */
          .vl-live-air-pollutant-row{grid-template-columns:minmax(0,1fr) var(--vl-action-size);grid-template-areas:'label label' 'value info';row-gap:6px}
          .vl-live-air-pollutant-label{grid-area:label}
          .vl-live-air-pollutant-value{grid-area:value;justify-self:start;min-width:0;text-align:start}
          .vl-live-air-pollutant-info{grid-area:info;justify-self:end}
          /* MOBILE: the 2-up weather stat grid becomes a single column so each stat gets a full,
             uncramped line. */
          .vl-live-wx-grid{grid-template-columns:1fr}
          .vl-live-air-history-head-meta{width:100%;justify-content:space-between}
          .vl-live-air-range{max-width:100%;overflow-x:auto}
          .vl-live-air-health-tab{scroll-snap-align:start}

        }
        @media(max-height:500px) and (orientation:landscape){
          .vl-live-map-shell{height:auto;min-height:250px}
          .vl-live-search-field{height:52px}
        }
        @media(min-width:701px) and (max-width:900px) and (orientation:portrait){
          .vl-live-air-card-wrap{width:min(416px,48%)}
          .vl-live-map-search{width:min(760px,100%)}
        }
        @media(prefers-reduced-motion:reduce){
          .vl-live *{scroll-behavior:auto!important;transition:none!important}
          .vl-live-cloud-field{animation:none!important}
        }

        @media(max-width:760px){
          .vl-live-tools{margin-top:22px;padding-top:22px}
          .vl-live-tools-layout{grid-template-columns:1fr;align-items:start;gap:28px}
          .vl-live-tool-card{padding:20px}
          .vl-live-world-pair{grid-template-columns:1fr;gap:14px}
          .vl-live-world-pair .vl-live-tool-swap{justify-self:center;margin-top:0}
          .vl-live-fx-pair{grid-template-columns:minmax(0,1fr) var(--vl-action-size) minmax(0,1fr);gap:10px}
          .vl-live-fx-pair .vl-live-tool-swap{margin-top:8px}
          .vl-live-route-metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
          .vl-live-route-metrics>div:first-child{grid-column:1/-1}
        }
      `}</style>
    </section>
  );
};

export default VayuLokLive;
