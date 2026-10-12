import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

/* ---------------------------------------------------------------------------------------
   deck.gl REGRESSION GUARD (formerly FEAT-002 dynamic-import mocks)
   ---------------------------------------------------------------------------------------
   The component NO LONGER imports deck.gl: both the AQI and PM2.5 heatmaps are Google
   ImageMapType tile overlays, and the old GoogleMapsOverlay/ScatterplotLayer dot-grid path
   (plus its grid fetch/cache) has been removed. These vi.mock factories and the recorder are
   kept as a REGRESSION GUARD: the component must never attach a deck.gl overlay, which the
   assertions `deckRec.overlaySetMapCalls.some(Boolean) === false` verify. If deck.gl is ever
   reintroduced the recorder will capture it; if these packages are later removed from the
   dependency tree, delete this block and those two assertions together. */
const deckRec = vi.hoisted( () => ( {
  overlaySetMapCalls: [] as unknown[],   // every arg passed to overlay.setMap(...)
  overlaySetPropsCalls: [] as { layers: unknown[] }[],
  overlayInstances: 0,
  scatterProps: [] as Record<string, any>[], // props of every ScatterplotLayer constructed
  reset() {
    this.overlaySetMapCalls = [];
    this.overlaySetPropsCalls = [];
    this.overlayInstances = 0;
    this.scatterProps = [];
  },
} ) );

vi.mock( '@deck.gl/google-maps', () => {
  class FakeGoogleMapsOverlay {
    _layers: unknown[] = [];
    constructor( _opts?: Record<string, unknown> ) { deckRec.overlayInstances += 1; }
    setMap( map: unknown ) { deckRec.overlaySetMapCalls.push( map ); }
    setProps( props: { layers: unknown[] } ) {
      this._layers = props.layers;
      deckRec.overlaySetPropsCalls.push( props );
    }
  }
  return { GoogleMapsOverlay: FakeGoogleMapsOverlay };
} );

vi.mock( '@deck.gl/layers', () => {
  class FakeScatterplotLayer {
    props: Record<string, any>;
    constructor( props: Record<string, any> ) {
      this.props = props;
      deckRec.scatterProps.push( props );
    }
  }
  return { ScatterplotLayer: FakeScatterplotLayer };
} );

/* Approved v8 spatial-dot palette. Real values determine the band; VayuLok caps
   the visual ramp at warm amber instead of introducing a red product accent. */
const VAYULOK_AQI_FILLS: Record<string, [ number, number, number, number ]> = {
  good: [ 61, 163, 90, 210 ],
  sat: [ 209, 244, 112, 210 ],
  mod: [ 232, 197, 71, 210 ],
  poor: [ 201, 138, 46, 210 ],
  worst: [ 201, 138, 46, 210 ],
};
function isRedDominant( fill: [ number, number, number, number ] ): boolean {
  return fill[ 0 ] > 200 && fill[ 1 ] < 80 && fill[ 2 ] < 80;
}
function matchesVayuLokRamp( fill: [ number, number, number, number ] ): boolean {
  return Object.values( VAYULOK_AQI_FILLS ).some(
    ramp => ramp[ 0 ] === fill[ 0 ] && ramp[ 1 ] === fill[ 1 ] && ramp[ 2 ] === fill[ 2 ],
  );
}

/* Return the declaration body ("{...}") of the rule that applies to `selector`, whether that
   selector owns a standalone block or sits ANYWHERE inside a comma-separated group. The component
   shares one "ONE ACTION-ICON SYSTEM" rule across several selectors (e.g.
   .vl-live-air-health-page-btn, .vl-live-air-health-tab, .vl-live-air-history-nav button{...}),
   so a naive /\.selector\{[^}]*\}/ match returns '' for every grouped selector except the one
   that happens to sit immediately before the '{'. This walks every "<selector-list>{<body>}" rule
   and returns the body of the first whose comma-separated selector list contains the exact
   target, so it is robust to grouping and to the selector's position within the group. */
function cssRuleFor( css: string, selector: string ): string {
  const target = selector.trim();
  // Strip CSS comments first so a /* ... */ before a grouped rule cannot be swallowed into the
  // preceding selector list and shift which "{...}" block a selector is attributed to.
  const clean = css.replace( /\/\*[\s\S]*?\*\//g, '' );
  const ruleRe = /([^{}]+)\{([^}]*)\}/g;
  const bodies: string[] = [];
  let m: RegExpExecArray | null;
  while ( ( m = ruleRe.exec( clean ) ) ) {
    const selectors = m[ 1 ].split( ',' ).map( s => s.trim() );
    if ( selectors.includes( target ) ) bodies.push( m[ 2 ] );
  }
  // A selector may legitimately appear in several grouped rules (base + :hover + transition…);
  // joining every matching body lets a single toContain() assertion find a declaration wherever
  // the component chose to place it, without caring about grouping order.
  return bodies.join( ';' );
}

/**
 * THE LIVE VAYULOK CONTENT, IN ISOLATION - the behaviour that is verifiable WITHOUT a browser,
 * a real Google key, or a *.wecare.digital origin.
 *
 * WHY THIS FILE EXISTS, AND WHY IT IMPORTS THE MODULE DYNAMICALLY
 * --------------------------------------------------------------
 * src/components/VayuLokLive.tsx reads the key ONCE, at module-evaluation time:
 *
 *     const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY || '';
 *
 * A top-level `import` would freeze that read at whatever the env was when the suite was first
 * loaded, so the key-absent and key-present cases could not both be exercised from one file. Each
 * case therefore stubs the env var FIRST, calls vi.resetModules(), and then `await import(...)`s a
 * fresh module instance so the module-scope read sees the stubbed value. This mirrors how the
 * component actually behaves in a build: the value is fixed when the chunk is evaluated.
 *
 * These are NOT static-value assertions. Every case drives the component's real effects - script
 * injection, fetch, the Google Maps stubs, the layer-control click - and would FAIL if the
 * degradation guard, the one-script-tag guard, or the on-user-action heatmap were reverted.
 */

const DUMMY_KEY = 'test-browser-key-not-a-real-credential';

// A minimal window.google.maps stub. It records what the component constructs and pushes, so the
// tests can assert on the real options the component passes rather than on duplicated literals.
interface MapsRecorder {
  mapOpts: Record<string, unknown> | null;
  overlayPushes: unknown[];
  overlayClears: number;
  // Live view of the array-backed overlayMapTypes double and the entries removed via removeAt,
  // so a test can observe teardown (the ImageMapType leaving the array / the removeAt path).
  overlayEntries: unknown[];
  overlayRemovals: unknown[];
  imageMapTypeOpts: Record<string, unknown>[];
  geocodeCalls: Record<string, unknown>[];
  autocompleteCalls: Record<string, unknown>[];
  placeFetchFields: string[][];
  // Every library name the component passed to google.maps.importLibrary. Production-like
  // Geocoder now arrives via importLibrary('geocoding'), so this proves the import happened.
  importedLibraries: string[];
  markerOpts: Record<string, unknown>[];
  fitBoundsCalls: { bounds: unknown; padding?: number }[];
  setZoomCalls: number[];
  mapClickHandler?: ( event: { latLng?: { lat: () => number; lng: () => number } } ) => void;
}

// Honest Place metadata the Places JS API may return. When provided, the stubbed Place
// carries these so the left-card metadata/attributes/description can be asserted; when
// omitted, the Place carries none and those lines must NOT render (honest conditional).
interface PlaceMetaStub {
  types?: string[];
  primaryTypeDisplayName?: string;
  rating?: number;
  userRatingCount?: number;
  websiteURI?: string;
  editorialSummary?: string;
}
interface InstallOpts {
  paintMap?: boolean;
  placeMeta?: PlaceMetaStub;
  // When false, DO NOT seed google.maps.Geocoder on the raw namespace. This reproduces the
  // real modern loader where Geocoder lives only in the 'geocoding' library, proving the
  // component obtains its Geocoder via importLibrary('geocoding') and not a pre-seeded ns.
  seedNamespaceGeocoder?: boolean;
  // Status the FakeGeocoder reports back to the component's geocode callback. Defaults to
  // 'OK'; set e.g. 'REQUEST_DENIED' to exercise the error-surfacing fallback.
  geocodeStatus?: string;
  geocodeRows?: unknown[];
  placeCountryCode?: string;
}

function installGoogleMaps( opts: boolean | InstallOpts = true ): MapsRecorder {
  const {
    paintMap = true,
    placeMeta,
    seedNamespaceGeocoder = true,
    geocodeStatus = 'OK',
    geocodeRows,
    placeCountryCode = 'IN',
  }: InstallOpts = typeof opts === 'boolean' ? { paintMap: opts } : opts;
  const rec: MapsRecorder = {
    mapOpts: null,
    overlayPushes: [],
    overlayClears: 0,
    overlayEntries: [],
    overlayRemovals: [],
    imageMapTypeOpts: [],
    geocodeCalls: [],
    autocompleteCalls: [],
    placeFetchFields: [],
    importedLibraries: [],
    markerOpts: [],
    fitBoundsCalls: [],
    setZoomCalls: [],
  };

  // An ARRAY-BACKED MVCArray-like double for map.overlayMapTypes. The production component's
  // detachHeatmap prefers the MVCArray contract: when getLength/getAt/removeAt are present it
  // walks the array from the end and removes only the entry === the stored ImageMapType. The
  // old {clear,push}-only stub forced the component down its clear() fallback, so the real
  // index-removal loop never ran under test. This double exposes push/getLength/getAt/removeAt
  // (and keeps clear() for any path that uses it) so the genuine removeAt path is exercised.
  // It preserves the existing recorder semantics: push still appends to rec.overlayPushes and
  // clear still bumps rec.overlayClears, so every existing assertion keeps working.
  const overlayEntries: unknown[] = [];
  const overlayMapTypes = {
    clear: () => { overlayEntries.length = 0; rec.overlayClears += 1; },
    push: ( t: unknown ) => { overlayEntries.push( t ); rec.overlayPushes.push( t ); },
    getLength: () => overlayEntries.length,
    getAt: ( i: number ) => overlayEntries[ i ],
    removeAt: ( i: number ) => {
      const [ removed ] = overlayEntries.splice( i, 1 );
      rec.overlayRemovals.push( removed );
      return removed;
    },
  };
  rec.overlayEntries = overlayEntries;

  class FakeMap {
    overlayMapTypes = overlayMapTypes;
    constructor( _el: HTMLElement, opts: Record<string, unknown> ) { rec.mapOpts = opts; }
    setCenter() { /* no-op */ }
    setZoom( zoom: number ) { rec.setZoomCalls.push( zoom ); }
    fitBounds( bounds: unknown, padding?: number ) { rec.fitBoundsCalls.push( { bounds, padding } ); }
    addListener( eventName: string, handler: ( event?: any ) => void ) {
      if ( eventName === 'tilesloaded' && paintMap ) requestAnimationFrame( () => handler() );
      if ( eventName === 'click' ) rec.mapClickHandler = handler;
      return { remove() { /* no-op */ } };
    }
  }
  class FakeMarker {
    constructor( opts: Record<string, unknown> ) { rec.markerOpts.push( opts ); }
    setPosition() { /* no-op */ }
    setTitle() { /* no-op */ }
    setMap() { /* no-op */ }
  }
  class FakeGeocoder {
    geocode(
      req: Record<string, unknown>,
      cb?: ( rows: unknown[] | null, status: string ) => void,
    ) {
      rec.geocodeCalls.push( req );
      // Reverse-geocode-on-click (location) and the address fallback both pass a callback.
      // Report the configured status; on OK return a single plausible India result so the
      // fallback's mapping path (results + 'idle') is exercised, not just the error branch.
      if ( typeof cb === 'function' ) {
        const rows = geocodeStatus === 'OK'
          ? ( geocodeRows || [ {
              formatted_address: 'Mumbai, Maharashtra, India',
              place_id: 'fake-place-id',
              geometry: { location: { lat: () => 19.076, lng: () => 72.8777 } },
              address_components: [
                { long_name: 'India', short_name: 'IN', types: [ 'country' ] },
              ],
            } ] )
          : null;
        cb( rows, geocodeStatus );
      }
    }
  }
  class FakeImageMapType {
    // Keep the constructor opts (name/opacity/getTileUrl/...) on the instance too, so a test
    // can identify WHICH overlay is live on the array-backed overlayMapTypes double by name,
    // not just inspect the recorded opts list. Both overlays now default-on, so tests need to
    // distinguish the AQI heatmap instance from the weather/storm instance after teardown.
    name?: unknown;
    opacity?: unknown;
    getTileUrl?: unknown;
    constructor( opts: Record<string, unknown> ) {
      rec.imageMapTypeOpts.push( opts );
      Object.assign( this, opts );
    }
  }
  class FakeAutocompleteSessionToken {}
  const fakePrediction = {
    mainText: { text: 'Mumbai' },
    secondaryText: { text: 'Maharashtra, India' },
    text: { toString: () => 'Mumbai, Maharashtra, India' },
    toPlace: () => ( {
      id: 'fake-place-id',
      displayName: 'Mumbai',
      formattedAddress: placeCountryCode === 'IN' ? 'Mumbai, Maharashtra, India' : 'Dhaka, Bangladesh',
      location: { lat: () => 19.076, lng: () => 72.8777 },
      viewport: { toJSON: () => ( { north: 19.18, south: 18.98, east: 72.99, west: 72.78 } ) },
      addressComponents: [
        { longText: placeCountryCode === 'IN' ? 'India' : 'Bangladesh', shortText: placeCountryCode, types: [ 'country' ] },
      ],
      // Honest metadata only when the test opts in; otherwise undefined so the
      // metadata/attributes/description lines must not render.
      ...( placeMeta || {} ),
      fetchFields: async ( req: { fields: string[] } ) => { rec.placeFetchFields.push( req.fields ); },
    } ),
  };
  const places = {
    AutocompleteSessionToken: FakeAutocompleteSessionToken,
    AutocompleteSuggestion: {
      fetchAutocompleteSuggestions: async ( req: Record<string, unknown> ) => {
        rec.autocompleteCalls.push( req );
        return { suggestions: [ { placePrediction: fakePrediction } ] };
      },
    },
  };

  const maps: Record<string, unknown> = {
    Map: FakeMap,
    Marker: FakeMarker,
    ImageMapType: FakeImageMapType,
    LatLng: class { constructor( _a: number, _b: number ) { /* no-op */ } },
    Size: class { constructor( _w: number, _h: number ) { /* no-op */ } },
    Point: class { constructor( _x: number, _y: number ) { /* no-op */ } },
    places,
    // Production-like modern loader: Geocoder is delivered by importLibrary('geocoding'),
    // mirroring how Google documents the geocoding library as separately imported. The
    // raw-namespace Geocoder is seeded ONLY when seedNamespaceGeocoder is true (legacy
    // loader), so a test can prove the component imports 'geocoding' rather than relying
    // on a pre-seeded namespace. Every requested library name is recorded.
    importLibrary: async ( name: string ) => {
      rec.importedLibraries.push( name );
      if ( name === 'places' ) return places;
      if ( name === 'maps' ) return { Map: FakeMap };
      if ( name === 'marker' ) return { Marker: FakeMarker };
      if ( name === 'geocoding' ) return { Geocoder: FakeGeocoder };
      if ( name === 'elevation' ) return {};
      return {};
    },
  };
  if ( seedNamespaceGeocoder ) maps.Geocoder = FakeGeocoder;

  ( window as unknown as { google: unknown } ).google = { maps };

  return rec;
}

function clearGoogleMaps() {
  delete ( window as unknown as { google?: unknown } ).google;
}

function removeScript() {
  document.getElementById( 'gmaps-js' )?.remove();
}

// Load a FRESH module instance after the env var has been stubbed, so the module-scope key read
// picks up the stubbed value.
async function loadComponent() {
  vi.resetModules();
  const mod = await import( '../components/VayuLokLive' );
  return mod.default;
}

let rec: MapsRecorder;

async function selectMumbai() {
  const input = await screen.findByRole( 'combobox' );
  fireEvent.change( input, { target: { value: 'Mumbai' } } );
  // The suggestion <li> commits the selection on `onPointerDown` (pointer events are the
  // component's chosen interaction so a touch/mouse tap recentres before blur closes the
  // list). fireEvent.mouseDown dispatches a `mousedown` event, which never invokes a React
  // `onPointerDown` handler, so `choose()` never ran and fitBounds was never called - this is
  // what left every selectMumbai()-driven test timing out. Fire pointerDown to match the DOM
  // contract, exactly as the standalone selection test at the bottom of this file already does.
  fireEvent.pointerDown( await screen.findByRole( 'option', { name: /Mumbai/i } ) );
  await waitFor( () => expect( rec.fitBoundsCalls.length ).toBeGreaterThan( 0 ) );
}

afterEach( () => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  removeScript();
  clearGoogleMaps();
  document.body.innerHTML = '';
  try { window.localStorage?.clear(); } catch { /* storage may be unavailable */ }
  vi.useRealTimers();
} );

// Reset the deck.gl recorder BEFORE each test. Doing it in beforeEach (rather than only in
// afterEach) means a prior test's unmount-cleanup setMap(null) - which fires during React
// Testing Library's own afterEach, after any reset there - cannot leak into this test.
beforeEach( () => {
  deckRec.reset();
} );

// A fetch stub that answers the Air Quality currentConditions:lookup (the grid + center
// sample) with a real-shaped payload and refuses everything else. `aqi` drives the parsed
// severity band; the stub is used by the deck.gl / gating tests below.
function requestUrl( input: RequestInfo | URL ): URL | null {
  try { return new URL( String( input ) ); } catch { return null; }
}

function requestIs( input: RequestInfo | URL, hostname: string, pathnamePrefix?: string ): boolean {
  const url = requestUrl( input );
  return Boolean( url && url.hostname === hostname && ( !pathnamePrefix || url.pathname.startsWith( pathnamePrefix ) ) );
}

function airConditionsFetch( aqi = 120, pm25 = 58 ) {
  return vi.fn( ( input: RequestInfo | URL, _init?: RequestInit ) => {
    const url = String( input );
    if ( requestIs( input, 'airquality.googleapis.com', '/v1/currentConditions' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          dateTime: new Date().toISOString(),
          indexes: [ { code: 'ind_cpcb', aqi, category: 'Moderate', dominantPollutant: 'pm25' } ],
          pollutants: [ { code: 'pm25', concentration: { value: pm25, units: 'MICROGRAMS_PER_CUBIC_METER' } } ],
          healthRecommendations: { generalPopulation: 'Limit prolonged outdoor exertion.' },
        } ),
      } as Response );
    }
    return Promise.resolve( { ok: false, json: async () => ( {} ) } as Response );
  } );
}

function environmentFetch() {
  const now = new Date();
  const hour = ( offset: number ) => new Date( now.getTime() + offset * 60 * 60 * 1000 ).toISOString();
  return vi.fn( ( input: RequestInfo | URL, _init?: RequestInit ) => {
    const url = String( input );
    if ( requestIs( input, 'airquality.googleapis.com', '/v1/currentConditions' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          dateTime: now.toISOString(),
          indexes: [ { code: 'ind_cpcb', displayName: 'India CPCB AQI', aqi: 74, category: 'Satisfactory', dominantPollutant: 'pm25' } ],
          pollutants: [
            { code: 'pm25', displayName: 'PM2.5', fullName: 'Fine particulate matter', concentration: { value: 28, units: 'MICROGRAMS_PER_CUBIC_METER' }, additionalInfo: { sources: 'Combustion of fuels in vehicles, power plants and industry.', effects: 'Penetrates deep into lungs and can trigger respiratory and cardiovascular problems.' } },
            { code: 'pm10', displayName: 'PM10', fullName: 'Inhalable particulate matter', concentration: { value: 44, units: 'MICROGRAMS_PER_CUBIC_METER' } },
          ],
          healthRecommendations: {
            generalPopulation: 'Google general guidance.',
            elderly: 'Google elderly guidance.',
            lungDiseasePopulation: 'Google lung guidance.',
            heartDiseasePopulation: 'Google heart guidance.',
            athletes: 'Google athlete guidance.',
            pregnantWomen: 'Google pregnancy guidance.',
            children: 'Google child guidance.',
          },
        } ),
      } as Response );
    }
    if ( requestIs( input, 'maps.googleapis.com', '/maps/api/timezone/json' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          status: 'OK',
          timeZoneId: 'Asia/Kolkata',
          timeZoneName: 'India Standard Time',
          rawOffset: 19800,
          dstOffset: 0,
        } ),
      } as Response );
    }
    if ( requestIs( input, 'weather.googleapis.com', '/v1/currentConditions' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          currentTime: now.toISOString(),
          temperature: { degrees: 26 },
          feelsLikeTemperature: { degrees: 27 },
          relativeHumidity: 68,
          wind: { speed: { value: 8, unit: 'KILOMETERS_PER_HOUR' }, direction: { degrees: 90 }, gust: { value: 12 } },
          precipitation: { probability: { percent: 10 }, qpf: { quantity: 0.4 } },
          uvIndex: 4,
          visibility: { distance: 11 },
          airPressure: { meanSeaLevelMillibars: 1009 },
          dewPoint: { degrees: 19 },
          cloudCover: 35,
          weatherCondition: { description: { text: 'Mostly sunny' } },
        } ),
      } as Response );
    }
    if ( requestIs( input, 'weather.googleapis.com', '/v1/forecast/hours' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          forecastHours: [ 0, 1, 2, 3, 4 ].map( i => ( {
            interval: { startTime: hour( i ) },
            temperature: { degrees: 26 + i },
            feelsLikeTemperature: { degrees: 27 + i },
            precipitation: { probability: { percent: 10 + i * 5 }, qpf: { quantity: i / 10 } },
            wind: { speed: { value: 8 + i, unit: 'KILOMETERS_PER_HOUR' }, direction: { degrees: 90 } },
            uvIndex: 4,
            weatherCondition: { description: { text: 'Mostly sunny' } },
          } ) ),
        } ),
      } as Response );
    }
    if ( requestIs( input, 'weather.googleapis.com', '/v1/history/hours' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          historyHours: Array.from( { length: 24 }, ( _, idx ) => {
            const offset = idx - 24;
            return {
              interval: { startTime: hour( offset ) },
              temperature: { degrees: 24 + ( idx % 4 ) },
              feelsLikeTemperature: { degrees: 25 + ( idx % 4 ) },
              precipitation: { probability: { percent: 5 }, qpf: { quantity: idx % 6 === 0 ? 0.3 : 0 } },
              wind: { speed: { value: 7, unit: 'KILOMETERS_PER_HOUR' }, direction: { degrees: 45 } },
              weatherCondition: { description: { text: 'Clear' } },
            };
          } ),
        } ),
      } as Response );
    }
    if ( requestIs( input, 'weather.googleapis.com', '/v1/forecast/days' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          forecastDays: [ {
            displayDate: { year: now.getUTCFullYear(), month: now.getUTCMonth() + 1, day: now.getUTCDate() },
            minTemperature: { degrees: 20 },
            maxTemperature: { degrees: 29 },
            daytimeForecast: { precipitation: { probability: { percent: 20 } }, weatherCondition: { description: { text: 'Partly cloudy' } } },
            sunEvents: { sunriseTime: hour( -6 ), sunsetTime: hour( 6 ) },
          } ],
        } ),
      } as Response );
    }
    if ( requestIs( input, 'weather.googleapis.com', '/v1/publicAlerts' ) ) {
      return Promise.resolve( { ok: true, json: async () => ( { weatherAlerts: [] } ) } as Response );
    }
    if ( requestIs( input, 'pollen.googleapis.com', '/v1/forecast' ) ) {
      return Promise.resolve( { ok: true, json: async () => ( { dailyInfo: [] } ) } as Response );
    }
    if ( requestIs( input, 'airquality.googleapis.com', '/v1/forecast' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          hourlyForecasts: Array.from( { length: 96 }, ( _, idx ) => idx + 1 ).map( i => ( {
            dateTime: hour( i ),
            indexes: [
              { code: 'ind_cpcb', displayName: 'India CPCB AQI', aqi: 70 + i, category: 'Satisfactory', dominantPollutant: 'pm25' },
              { code: 'uaqi', displayName: 'Universal AQI', aqi: 60 + i, aqiDisplay: String( 60 + i ), category: 'Good air quality', dominantPollutant: 'pm25' },
            ],
            pollutants: [ {
              code: 'pm25',
              displayName: 'PM2.5',
              fullName: 'Fine particulate matter',
              concentration: { value: 25 + i, units: 'MICROGRAMS_PER_CUBIC_METER' },
              additionalInfo: { sources: 'Forecast source information.', effects: 'Forecast health effect information.' },
            } ],
            healthRecommendations: { generalPopulation: 'Forecast health recommendation.' },
          } ) ),
        } ),
      } as Response );
    }
    if ( requestIs( input, 'airquality.googleapis.com', '/v1/history' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          hoursInfo: [ {
            dateTime: hour( -1 ),
            indexes: [ { code: 'ind_cpcb', aqi: 72 } ],
            pollutants: [ { code: 'pm25', concentration: { value: 27, units: 'MICROGRAMS_PER_CUBIC_METER' } } ],
          } ],
        } ),
      } as Response );
    }
    return Promise.resolve( { ok: false, json: async () => ( {} ) } as Response );
  } );
}


describe( 'VayuLokLive v8 approved design contract', () => {

  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
    rec = installGoogleMaps();
  } );

  it( 'loads a destination-only global hybrid map and omits the removed map pills', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    expect( rec.mapOpts?.restriction ).toBeUndefined();
    expect( rec.mapOpts?.center ).toEqual( { lat: 25, lng: 86 } );
    expect( rec.mapOpts?.zoom ).toBe( 4 );
    expect( rec.mapOpts?.mapTypeId ).toBe( 'hybrid' );
    expect( rec.mapOpts?.gestureHandling ).toBe( 'none' );
    expect( rec.mapOpts?.draggable ).toBe( false );
    expect( rec.mapOpts?.scrollwheel ).toBe( false );
    expect( rec.mapOpts?.disableDoubleClickZoom ).toBe( true );
    expect( rec.mapOpts?.zoomControl ).toBe( false );
    expect( rec.mapClickHandler ).toBeUndefined();

    expect( container.querySelector( '.vl-live-place-card' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-left' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-layers' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-selected-label' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-map-locate' ) ).toBeNull();
    expect( screen.queryByText( 'Search India to see live weather and air.' ) ).toBeNull();
    await waitFor( () => expect( fetchSpy ).toHaveBeenCalled() );
  } );

  it( 'search selection recenters the map and keeps only the map marker, not a bottom pill', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    expect( container.querySelector( '.vl-live-selected-label' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-layers' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-place-card' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-map-locate' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-map-destbar-chevron' ) ).toBeNull();

    await waitFor( () => expect( rec.markerOpts.length ).toBeGreaterThan( 0 ) );
    const icon = rec.markerOpts[ 0 ].icon;
    expect( typeof icon ).toBe( 'string' );
    const decodedIcon = decodeURIComponent( String( icon ) );
    expect( decodedIcon ).toContain( '#1a3a2a' );
    expect( decodedIcon ).toContain( '#d1f470' );
    expect( decodedIcon ).toContain( 'M480-480q33 0 56.5-23.5' );
    expect( decodedIcon ).toContain( 'width="36" height="36"' );
    expect( decodedIcon ).not.toContain( 'M19 0C8.5 0 0 8.5' );
    expect( rec.fitBoundsCalls[ 0 ].padding ).toBe( 56 );
  } );

  it( 'overlays a floating Air Quality card on the map (no left place panel) with the title and the Air/Weather toggle', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    // The floating card lives INSIDE the map shell, so it genuinely overlays the map.
    const card = await waitFor( () => {
      const el = container.querySelector( '.vl-live-map-shell .vl-live-air-card' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( card.querySelector( '.vl-live-air-card-title' ) ).toBeNull();
    const context = card.querySelector( '.vl-live-air-context' );
    expect( context ).not.toBeNull();
    expect( context?.textContent ).toContain( 'Mumbai' );
    expect( context?.textContent ).toContain( 'IST' );

    // The whole former left panel is gone.
    expect( container.querySelector( '.vl-live-left' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-place-card' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-photo-rail' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-forecast-weather' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-air-source-strip' ) ).toBeNull();

    // The toggle is a two-tab tablist with Air selected by default.
    const airTab = await screen.findByRole( 'tab', { name: 'Air' } );
    const weatherTab = await screen.findByRole( 'tab', { name: 'Weather' } );
    expect( airTab ).toHaveAttribute( 'aria-selected', 'true' );
    expect( weatherTab ).toHaveAttribute( 'aria-selected', 'false' );
  } );

  it( 'shows AQI context, inline dominant metadata and pollutant details with one Material icon language', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    // The Air panel renders only once live `air` has arrived. environmentFetch()
    // returns aqi 74 / Satisfactory with pm25 + pm10 pollutants and dominant pm25.
    const panel = await waitFor( () => {
      const el = container.querySelector( '[aria-label="Air details"]' );
      expect( el ).not.toBeNull();
      expect( el?.textContent ).toContain( 'Satisfactory' );
      return el as HTMLElement;
    } );

    // AQI summary follows the homepage hue language: a free AQI number + the same
    // green/blue/purple accent spine as home-flow. No circular ring/gauge remains.
    expect( panel.querySelector( '.vl-live-air-aqi-number' )?.textContent ).toBe( '74' );
    expect( panel.querySelector( '.vl-live-air-aqi-unit' )?.textContent ).toBe( 'AQI' );
    expect( panel.querySelector( '.vl-live-air-gauge-word' )?.textContent ).toContain( 'Satisfactory' );
    expect( panel.querySelector( '.vl-live-air-aqi-spine' ) ).not.toBeNull();
    expect( panel.querySelector( '.vl-live-air-gauge-svg' ) ).toBeNull();
    expect( panel.querySelector( '.vl-live-air-gauge-arc' ) ).toBeNull();
    // AQI metadata is one quiet row under the homepage-scale category heading: an "AQI <n>"
    // chip and a "Dominant <pollutant>" chip, each with a leading Material icon, plus the
    // update age. The index-name ("India CPCB AQI"/"NAQI") and the Universal AQI line were
    // intentionally removed so the row reads AQI + Dominant only.
    const summaryMeta = panel.querySelector( '.vl-live-air-summary-meta' );
    expect( summaryMeta?.textContent ).toContain( 'AQI' );
    expect( summaryMeta?.textContent ).not.toContain( 'India CPCB AQI' );
    expect( summaryMeta?.textContent ).not.toContain( 'Universal AQI' );
    expect( summaryMeta?.textContent ).toContain( 'Dominant' );
    expect( summaryMeta?.textContent ).toContain( 'PM2.5' );
    expect( summaryMeta?.textContent ).not.toContain( 'pm25' );
    expect( summaryMeta?.textContent ).toMatch( /Updated/ );
    // The AQI and Dominant chips now each carry a leading icon.
    expect( summaryMeta?.querySelectorAll( '.vl-live-air-summary-chip svg' ).length ).toBe( 2 );
    expect( panel.querySelector( '.vl-live-air-dominant' ) ).toBeNull();
    expect( panel.querySelector( '.vl-live-air-index-name' ) ).toBeNull();
    expect( panel.querySelector( '.vl-live-air-fact' ) ).toBeNull();

    // Pollutant rows keep value + unit + label, and the info control uses the supplied
    // Google Material Symbols icon rather than a hand-drawn circle/i glyph.
    const rows = panel.querySelectorAll( '.vl-live-air-pollutant-row' );
    expect( rows.length ).toBeGreaterThan( 0 );
    const firstRow = rows[ 0 ] as HTMLElement;
    expect( firstRow.querySelector( '.vl-live-air-pollutant-value' )?.textContent ).toMatch( /\d/ );
    expect( firstRow.querySelector( '.vl-live-air-pollutant-label' )?.textContent?.length ).toBeGreaterThan( 0 );
    const info = firstRow.querySelector( '.vl-live-air-pollutant-info' ) as HTMLButtonElement;
    expect( info ).not.toBeNull();
    expect( info.tagName ).toBe( 'BUTTON' );
    expect( info.querySelector( 'svg' )?.getAttribute( 'viewBox' ) ).toBe( '0 -960 960 960' );
    expect( info.querySelector( 'path' )?.getAttribute( 'd' )?.length ).toBeGreaterThan( 100 );

    // Tooltip is created only while active, and is OUTSIDE the scrollable Air card.
    fireEvent.focus( info );
    const describedBy = await waitFor( () => {
      const id = info.getAttribute( 'aria-describedby' );
      expect( id ).toBeTruthy();
      return id as string;
    } );
    const tip = document.getElementById( describedBy );
    expect( tip ).not.toBeNull();
    expect( tip?.getAttribute( 'role' ) ).toBe( 'dialog' );
    expect( tip?.querySelector( '[aria-label="Close pollutant details"]' ) ).not.toBeNull();
    expect( tip?.closest( '.vl-live-air-card' ) ).toBeNull();
    expect( tip?.textContent ).toContain( 'PM2.5' );
    expect( tip?.textContent ).toContain( 'Fine particulate matter' );
    expect( tip?.textContent ).toContain( 'Sources' );
    expect( tip?.textContent ).toContain( 'Combustion of fuels' );
    expect( tip?.textContent ).toContain( 'Effects' );
    expect( tip?.textContent ).toContain( 'Penetrates deep into lungs' );

    // Explicit close button removes the viewport-level popup without relying on hover/blur.
    const closeButton = tip?.querySelector( '[aria-label="Close pollutant details"]' ) as HTMLButtonElement;
    fireEvent.click( closeButton );
    await waitFor( () => expect( document.getElementById( describedBy ) ).toBeNull() );

    // Re-open and Escape closes it too.
    fireEvent.focus( info );
    await waitFor( () => expect( document.getElementById( describedBy ) ).not.toBeNull() );
    fireEvent.keyDown( document, { key: 'Escape' } );
    await waitFor( () => expect( document.getElementById( describedBy ) ).toBeNull() );

    // Re-open and an outside pointer closes it.
    fireEvent.focus( info );
    await waitFor( () => expect( document.getElementById( describedBy ) ).not.toBeNull() );
    fireEvent.pointerDown( document.body );
    await waitFor( () => expect( document.getElementById( describedBy ) ).toBeNull() );

    // No additionalInfo -> honest value/unit fallback, never invented Sources/Effects.
    fireEvent.blur( info );
    const pm10Row = Array.from( rows ).find(
      r => ( r.querySelector( '.vl-live-air-pollutant-label' )?.textContent ?? '' ).includes( 'PM10' )
    ) as HTMLElement;
    expect( pm10Row ).toBeTruthy();
    const pm10Info = pm10Row.querySelector( '.vl-live-air-pollutant-info' ) as HTMLButtonElement;
    fireEvent.focus( pm10Info );
    const pm10Id = await waitFor( () => {
      const id = pm10Info.getAttribute( 'aria-describedby' );
      expect( id ).toBeTruthy();
      return id as string;
    } );
    const pm10Tip = document.getElementById( pm10Id );
    expect( pm10Tip?.textContent ).toContain( 'PM10' );
    expect( pm10Tip?.textContent ).toMatch( /\d/ );
    expect( pm10Tip?.textContent ).not.toContain( 'Sources' );
    expect( pm10Tip?.textContent ).not.toContain( 'Effects' );
    fireEvent.blur( pm10Info );

    // The unit symbol carries a plain-language expansion as a title, so a reader who does not
    // know the abbreviation can still understand it (µg/m³ -> micrograms per cubic metre).
    const pm25Unit = firstRow.querySelector( '.vl-live-air-pollutant-value small' );
    expect( pm25Unit?.getAttribute( 'title' ) ).toBe( 'micrograms per cubic metre' );

    // NO RED anywhere in the rendered card markup/styles.
    expect( container.innerHTML ).not.toContain( 'dc2626' );

    // Toggle to Weather: aria-selected flips and an inert placeholder panel appears,
    // with no invented weather data.
    const airTab = await screen.findByRole( 'tab', { name: 'Air' } );
    const weatherTab = await screen.findByRole( 'tab', { name: 'Weather' } );
    expect( airTab ).toHaveAttribute( 'aria-selected', 'true' );

    fireEvent.click( weatherTab );
    await waitFor( () => expect( weatherTab ).toHaveAttribute( 'aria-selected', 'true' ) );
    expect( airTab ).toHaveAttribute( 'aria-selected', 'false' );
    const weatherPanel = container.querySelector( '[aria-label="Weather details"]' );
    expect( weatherPanel ).not.toBeNull();
    // The Weather tab now renders the real current-conditions dashboard from the already-fetched
    // weather data (environmentFetch returns 26°, feels 27, humidity 68, "Mostly sunny").
    await waitFor( () => {
      expect( weatherPanel?.querySelector( '.vl-live-wx-now-temp' )?.textContent ).toContain( '26°' );
    } );
    expect( weatherPanel?.querySelector( '.vl-live-wx-now-cond' )?.textContent ).toContain( 'Mostly sunny' );
    expect( weatherPanel?.textContent ).not.toMatch( /coming soon/i );
    // The Air panel is no longer shown while Weather is selected.
    expect( container.querySelector( '[aria-label="Air details"]' ) ).toBeNull();
  } );

  it( 'renders the full Weather dashboard (metrics grid, hourly, 10-day, 24h history, neutral alerts)', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    fireEvent.click( await screen.findByRole( 'tab', { name: 'Weather' } ) );
    const panel = await waitFor( () => {
      const el = container.querySelector( '[aria-label="Weather details"]' );
      expect( el?.querySelector( '.vl-live-wx-now-temp' ) ).not.toBeNull();
      return el as HTMLElement;
    } );

    // Current metrics grid shows only returned fields.
    expect( panel.querySelector( '.vl-live-wx-grid' ) ).not.toBeNull();
    expect( panel.textContent ).toContain( 'Humidity' );
    expect( panel.textContent ).toContain( 'Wind' );
    // Hourly forecast strip with 24h/48h range.
    expect( panel.querySelector( '.vl-live-air-forecast-strip' ) ).not.toBeNull();
    expect( within( panel ).getByRole( 'group', { name: 'Weather forecast range' } ) ).toBeTruthy();
    // 10-day rows.
    expect( panel.querySelector( '.vl-live-wx-daily-row' ) ).not.toBeNull();
    // 24h history with a metric toggle.
    expect( within( panel ).getByRole( 'group', { name: 'Weather history metric' } ) ).toBeTruthy();
    // Alerts: India has no coverage, so the neutral line shows (not an empty noisy panel).
    expect( panel.textContent ).toContain( 'No active weather or hazard alerts' );
    // The publicAlerts request IS now issued (coverage is per-region; India 404s, covered
    // regions 200 with an array). With the mock returning an empty array, the neutral line shows.
    await waitFor( () => expect( fetchSpy.mock.calls.some( call => requestIs( call[ 0 ] as RequestInfo | URL, 'weather.googleapis.com', '/v1/publicAlerts' ) ) ).toBe( true ) );
    // Raw temperature value carries data-wc-no-translate (keeps numbers honest under translation).
    expect( panel.querySelector( '.vl-live-wx-now-temp' )?.getAttribute( 'data-wc-no-translate' ) ).toBe( 'true' );
    // NO RED.
    expect( container.innerHTML ).not.toContain( 'dc2626' );
  } );

  it( 'renders a live weather public alert with its title, area and source attribution', async () => {
    const base = environmentFetch();
    const withAlert = vi.fn( ( input: RequestInfo | URL, init?: RequestInit ) => {
      if ( requestIs( input, 'weather.googleapis.com', '/v1/publicAlerts' ) ) {
        return Promise.resolve( { ok: true, json: async () => ( {
          regionCode: 'IN',
          weatherAlerts: [ {
            alertId: 'a1', alertTitle: 'Flash Flood Warning', eventType: 'FLASH_FLOOD',
            areaName: 'East Khasi Hills', severity: 'SEVERE', urgency: 'IMMEDIATE',
            instruction: 'Avoid low-lying roads and flooded crossings.',
            dataSource: 'India Meteorological Department', expirationTime: '2026-10-12T12:00:00Z',
          } ],
        } ) } as Response );
      }
      return base( input, init );
    } );
    vi.stubGlobal( 'fetch', withAlert );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();
    fireEvent.click( await screen.findByRole( 'tab', { name: 'Weather' } ) );

    const alert = await waitFor( () => {
      const el = container.querySelector( '.vl-live-wx-alert' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( alert.textContent ).toContain( 'Flash Flood Warning' );
    expect( alert.textContent ).toContain( 'East Khasi Hills' );
    expect( alert.textContent ).toContain( 'Avoid low-lying roads' );
    // Google requires source attribution whenever an alert is shown.
    expect( alert.textContent ).toContain( 'India Meteorological Department' );
    // Severity drives the styling class (amber/dark, never red).
    expect( alert.className ).toContain( 'sev-severe' );
    expect( container.innerHTML ).not.toContain( 'dc2626' );
  } );

  it( 'renders pollutant concentrations faithfully: a real 0.4 stays 0.4, 0.04 stays 0.04, exact 0 stays 0', async () => {
    // Google returns precise concentrations. Blindly rounding a real trace (0.4) to "0" would read
    // as "no pollutant" and misrepresent the measurement, so sub-1 values keep their significant
    // decimals (0.4 ppb -> "0.4 ppb", 0.04 ppm -> "0.04 ppm") rather than being flattened to 0 or
    // an invented "<1"; a genuine 0 stays "0"; values >= 1 round to an integer.
    const traceFetch = vi.fn( ( input: RequestInfo | URL ) => {
      if ( requestIs( input, 'airquality.googleapis.com', '/v1/currentConditions' ) ) {
        return Promise.resolve( {
          ok: true,
          json: async () => ( {
            dateTime: new Date().toISOString(),
            indexes: [ { code: 'ind_cpcb', displayName: 'India CPCB AQI', aqi: 41, category: 'Good', dominantPollutant: 'co' } ],
            pollutants: [
              { code: 'no2', displayName: 'NO2', concentration: { value: 0, units: 'PARTS_PER_BILLION' } },
              { code: 'so2', displayName: 'SO2', concentration: { value: 0.4, units: 'PARTS_PER_BILLION' } },
              { code: 'co', displayName: 'CO', concentration: { value: 0.04, units: 'PARTS_PER_MILLION' } },
              { code: 'pm25', displayName: 'PM2.5', concentration: { value: 32, units: 'MICROGRAMS_PER_CUBIC_METER' } },
            ],
          } ),
        } as Response );
      }
      return Promise.resolve( { ok: true, json: async () => ( {} ) } as Response );
    } );
    vi.stubGlobal( 'fetch', traceFetch );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    const rows = await waitFor( () => {
      const found = container.querySelectorAll( '.vl-live-air-pollutant-row' );
      expect( found.length ).toBeGreaterThan( 0 );
      return found;
    } );
    const valueOf = ( label: string ) => Array.from( rows )
      .find( r => ( r.querySelector( '.vl-live-air-pollutant-label' )?.textContent ?? '' ).includes( label ) )
      ?.querySelector( '.vl-live-air-pollutant-value' )?.textContent?.trim() ?? '';
    expect( valueOf( 'NO2' ) ).toMatch( /^0\s/ );        // exact zero stays 0
    expect( valueOf( 'SO2' ) ).toContain( '0.4' );         // real trace preserved, not rounded to 0
    expect( valueOf( 'SO2' ) ).not.toContain( '<1' );      // and NOT replaced by a placeholder
    expect( valueOf( 'CO' ) ).toContain( '0.04' );         // two significant decimals preserved
    expect( valueOf( 'PM2.5' ) ).toMatch( /^32\s/ );
  } );

  it( 'links the search combobox to its active option via aria-activedescendant', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    const input = await screen.findByRole( 'combobox' );
    // No active option before any results, so no activedescendant is advertised.
    expect( input.getAttribute( 'aria-activedescendant' ) ).toBeFalsy();
    fireEvent.change( input, { target: { value: 'Mumbai' } } );
    const option = await screen.findByRole( 'option', { name: /Mumbai/i } );
    await waitFor( () =>
      expect( input.getAttribute( 'aria-activedescendant' ) ).toBe( option.id ) );
    expect( option.id ).toMatch( /^vl-live-search-option-\d+$/ );
  } );

  it( 'adds a heatmap toggle, Poor/Excellent legend, health persona tablist and an hourly-history chart to the Air panel', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    // The Air panel is present once live air has arrived.
    await waitFor( () => {
      const el = container.querySelector( '[aria-label="Air details"]' );
      expect( el ).not.toBeNull();
      expect( el?.textContent ).toContain( 'Satisfactory' );
    } );

    // (1) HEATMAP. This is the only map-visual switch now. It stays ON by default, drives
    //     the continuous Google Air Quality tile layer and uses the requested Material
    //     Symbols "switches" glyph.
    const heatSwitch = await screen.findByRole( 'switch', { name: 'Air quality heatmap' } );
    expect( heatSwitch ).toHaveAttribute( 'aria-checked', 'true' );
    expect( heatSwitch ).not.toBeDisabled();
    expect( heatSwitch.querySelector( 'svg' )?.getAttribute( 'viewBox' ) ).toBe( '0 -960 960 960' );
    expect( heatSwitch.querySelector( 'path' )?.getAttribute( 'd' )?.length ).toBeGreaterThan( 100 );
    expect( screen.queryByRole( 'switch', { name: 'Weather storm overlay' } ) ).toBeNull();
    // DEFAULT-ON: the AQI heatmap tile overlay is wired onto the map BY DEFAULT, with no
    // click required, as soon as the keyed map is ready.
    await waitFor( () => {
      expect( rec.imageMapTypeOpts.length ).toBeGreaterThan( 0 );
      expect( rec.overlayPushes.length ).toBeGreaterThan( 0 );
    } );
    // AQI tiles do not paint deck.gl scatter dots.
    expect( deckRec.overlaySetMapCalls.some( value => Boolean( value ) ) ).toBe( false );

    // One of the recorded ImageMapTypes is the AQI heatmap: its getTileUrl returns a Google
    // Air Quality heatmap tile URL on the UAQI_RED_GREEN map type, carrying the key.
    const aqiOpts = rec.imageMapTypeOpts.find( o => {
      const g = o.getTileUrl as ( ( coord: { x: number; y: number }, zoom: number ) => string ) | undefined;
      return typeof g === 'function' && g( { x: 1, y: 2 }, 5 ).includes( 'mapTypes/UAQI_RED_GREEN/heatmapTiles' );
    } )!;
    expect( aqiOpts ).toBeTruthy();
    const getTileUrl = aqiOpts.getTileUrl as (
      coord: { x: number; y: number }, zoom: number,
    ) => string;
    expect( typeof getTileUrl ).toBe( 'function' );
    const tileUrl = getTileUrl( { x: 1, y: 2 }, 5 );
    expect( tileUrl ).toContain( 'airquality.googleapis.com' );
    expect( tileUrl ).toContain( 'mapTypes/UAQI_RED_GREEN/heatmapTiles' );
    expect( tileUrl ).toContain( 'key=' );

    // TEARDOWN: flipping the Heatmap switch OFF (layer -> null) detaches the AQI heatmap
    // via the production removeAt index-removal loop. The atmosphere is not an ImageMapType.
    const overlayCountBeforeOff = rec.overlayEntries.length;
    await waitFor( () => {
      const sw = screen.getByRole( 'switch', { name: 'Air quality heatmap' } );
      if ( sw.getAttribute( 'aria-checked' ) !== 'false' ) fireEvent.click( sw );
      expect( sw ).toHaveAttribute( 'aria-checked', 'false' );
    } );
    // Turning the heatmap OFF removes the AQI tile overlay.
    await waitFor( () => {
      expect( rec.overlayRemovals.length ).toBeGreaterThan( 0 );
      expect( rec.overlayEntries.length ).toBe( overlayCountBeforeOff - 1 );
    } );

    // Re-toggle ON re-pushes exactly one AQI instance (idempotent attach, no duplicate).
    await waitFor( () => {
      const sw = screen.getByRole( 'switch', { name: 'Air quality heatmap' } );
      if ( sw.getAttribute( 'aria-checked' ) !== 'true' ) fireEvent.click( sw );
      expect( sw ).toHaveAttribute( 'aria-checked', 'true' );
    } );
    await waitFor( () => expect( rec.overlayEntries.length ).toBe( overlayCountBeforeOff ) );

    const legend = container.querySelector( '.vl-live-air-heatmap-legend' );
    expect( legend?.textContent ).toContain( 'Poor' );
    expect( legend?.textContent ).toContain( 'Excellent' );

    // (2) HEALTH RECOMMENDATIONS. All seven groups come from Google's live
    // healthRecommendations payload. There is no static WECARE recommendation fallback.
    const healthTablist = screen.getByRole( 'tablist', { name: 'Health recommendation profiles' } );
    const personaTabs = healthTablist.querySelectorAll( '[role="tab"]' );
    expect( personaTabs ).toHaveLength( 7 );
    expect( screen.getByRole( 'tab', { name: 'General population' } ) ).toBeTruthy();
    expect( screen.getByRole( 'tab', { name: 'Elderly' } ) ).toBeTruthy();
    expect( screen.getByRole( 'tab', { name: 'Lung disease' } ) ).toBeTruthy();
    expect( screen.getByRole( 'tab', { name: 'Heart disease' } ) ).toBeTruthy();
    expect( screen.getByRole( 'tab', { name: 'Athletes' } ) ).toBeTruthy();
    expect( screen.getByRole( 'tab', { name: 'Pregnant women' } ) ).toBeTruthy();
    expect( screen.getByRole( 'tab', { name: 'Children' } ) ).toBeTruthy();

    // Health icons stay in one horizontal row; text labels are tooltip/ARIA only, not stacked
    // under each icon. Pager arrows cycle the active profile.
    expect( healthTablist.querySelectorAll( '.vl-live-air-health-tab-label' ) ).toHaveLength( 0 );
    const prevHealth = screen.getByRole( 'button', { name: 'Previous health recommendation' } );
    const nextHealth = screen.getByRole( 'button', { name: 'Next health recommendation' } );
    expect( prevHealth ).toBeTruthy();
    expect( nextHealth ).toBeTruthy();
    expect( container.querySelector( '.vl-live-air-health-page-count' ) ).toBeNull();

    const css = Array.from( container.querySelectorAll( 'style' ) ).map( s => s.textContent || '' ).join( '\n' );
    const healthBtnRule = cssRuleFor( css, '.vl-live-air-health-page-btn' );
    const healthTabRule = cssRuleFor( css, '.vl-live-air-health-tab' );
    const historyBtnRule = cssRuleFor( css, '.vl-live-air-history-nav button' );
    expect( healthBtnRule ).toContain( 'width:var(--vl-action-size)' );
    expect( healthBtnRule ).toContain( 'height:var(--vl-action-size)' );
    expect( healthBtnRule ).toContain( 'border-radius:50%' );
    expect( healthBtnRule ).toContain( 'background:var(--lime)' );
    expect( healthBtnRule ).toContain( 'color:var(--green)' );
    expect( healthTabRule ).toContain( 'width:var(--vl-action-size)' );
    expect( healthTabRule ).toContain( 'border-radius:50%' );
    expect( historyBtnRule ).toContain( 'width:var(--vl-action-size)' );
    expect( historyBtnRule ).toContain( 'border-radius:50%' );

    const hoverRule = css.match( /\.vl-live-air-pollutant-info:hover,[\s\S]*?\{[^}]*\}/ )?.[ 0 ] || '';
    expect( hoverRule ).toContain( 'background:var(--lime-hover)' );
    expect( hoverRule ).toContain( 'border:0' );
    expect( hoverRule ).toContain( 'box-shadow:0 6px 14px rgba(26,58,42,.16)' );
    expect( hoverRule ).toContain( 'transform:translateY(-2px) scale(1.04)' );
    expect( hoverRule ).not.toContain( 'background:var(--green)' );

    const personaRule = css.match( /\.vl-live-air-health-persona\{[^}]*\}/ )?.[ 0 ] || '';
    expect( personaRule ).toContain( 'font-size:var(--vl-card-heading-size)' );
    expect( personaRule ).toContain( 'font-weight:var(--vl-card-heading-weight)' );
    expect( personaRule ).toContain( 'letter-spacing:var(--vl-card-heading-track)' );
    const healthTextRule = css.match( /\.vl-live-air-health-text\{[^}]*\}/ )?.[ 0 ] || '';
    expect( healthTextRule ).toContain( 'font-size:var(--vl-body-size)' );
    expect( healthTextRule ).toContain( 'font-weight:var(--vl-body-weight)' );
    expect( healthTextRule ).toContain( 'line-height:var(--vl-body-lh)' );
    expect( healthTextRule ).toContain( 'letter-spacing:var(--vl-body-track)' );
    expect( css ).toContain( '--vl-card-heading-size:22px' );
    expect( css ).toContain( '--vl-body-size:20px' );

    const selected = Array.from( personaTabs ).filter( t => t.getAttribute( 'aria-selected' ) === 'true' );
    expect( selected ).toHaveLength( 1 );
    expect( selected[ 0 ].querySelector( '.vl-live-air-health-icon' )?.getAttribute( 'viewBox' ) ).toBe( '0 -960 960 960' );

    const healthPanel = container.querySelector( '.vl-live-air-health-panel' );
    const firstLiveText = healthPanel?.querySelector( '.vl-live-air-health-text' )?.textContent ?? '';
    expect( firstLiveText ).toMatch( /Google .* guidance/ );

    const selectedBeforePager = Array.from( personaTabs ).findIndex( t => t.getAttribute( 'aria-selected' ) === 'true' );
    fireEvent.click( nextHealth );
    await waitFor( () => {
      const selectedAfterPager = Array.from( personaTabs ).findIndex( t => t.getAttribute( 'aria-selected' ) === 'true' );
      expect( selectedAfterPager ).toBe( ( selectedBeforePager + 1 ) % 7 );
    } );

    const athleteTab = screen.getByRole( 'tab', { name: 'Athletes' } );
    fireEvent.click( athleteTab );
    await waitFor( () => expect( athleteTab ).toHaveAttribute( 'aria-selected', 'true' ) );
    expect( healthPanel?.querySelector( '.vl-live-air-health-text' )?.textContent ).toBe( 'Google athlete guidance.' );

    const pregnantTab = screen.getByRole( 'tab', { name: 'Pregnant women' } );
    fireEvent.click( pregnantTab );
    await waitFor( () => expect( pregnantTab ).toHaveAttribute( 'aria-selected', 'true' ) );
    expect( healthPanel?.querySelector( '.vl-live-air-health-text' )?.textContent ).toBe( 'Google pregnancy guidance.' );

    // (3) HOURLY HISTORY. Title + destination-local timestamp derived from real data +
    //     a role=img chart with current value and a visible current-value marker.
    expect( screen.getByText( 'Hourly History' ) ).toBeTruthy();
    const chart = await waitFor( () => {
      const el = container.querySelector( '.vl-live-air-history-chart' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    // The chart is a keyboard-operable slider over the history points: focusable, with
    // aria-value* describing the inspected position.
    expect( chart.getAttribute( 'role' ) ).toBe( 'slider' );
    expect( chart.getAttribute( 'tabindex' ) ).toBe( '0' );
    expect( chart.getAttribute( 'aria-label' ) ).toMatch( /AQI history/ );
    expect( chart.getAttribute( 'aria-valuetext' ) ).toMatch( /AQI \d+/ );
    // The reading date/time moved out of the header and below the chart, styled as a lime-tinted
    // pill with a leading clock icon in the site accent colour; the on-chart AQI value bubble was
    // removed (the chart no longer prints the raw number).
    const historyStamp = container.querySelector( '.vl-live-air-history-stamp' );
    expect( historyStamp?.textContent ).toMatch( /IST/ );
    expect( historyStamp?.querySelector( '.vl-live-air-history-stamp-icon' ) ).not.toBeNull();
    expect( container.querySelector( '.vl-live-air-history-bubble' ) ).toBeNull();
    const stampRule = css.match( /\.vl-live-air-history-stamp\{[^}]*\}/ )?.[ 0 ] || '';
    expect( stampRule ).toContain( 'background:var(--lime-tint)' );
    expect( stampRule ).toContain( 'color:var(--green)' );
    expect( stampRule ).toContain( 'border-radius:var(--pill-r)' );
    // It sits below the chart, not inside the header row.
    expect( container.querySelector( '.vl-live-air-history-head .vl-live-air-history-stamp' ) ).toBeNull();
    const historyNav = container.querySelector( '.vl-live-air-history-head .vl-live-air-history-nav' );
    expect( historyNav ).not.toBeNull();
    expect( historyNav?.querySelectorAll( 'button' ) ).toHaveLength( 2 );
    historyNav?.querySelectorAll( 'svg' ).forEach( svg => {
      expect( svg.getAttribute( 'viewBox' ) ).toBe( '0 -960 960 960' );
    } );

    // Pointer inspection surfaces the specific hour's local time (the visible tooltip shows only
    // the time; the AQI is carried in the chart's aria-valuetext and the sr-only live region).
    expect( chart.getAttribute( 'aria-label' ) ).toContain( 'Use arrow keys to inspect an hour.' );
    fireEvent.pointerDown( chart, { clientX: 0, pointerType: 'touch' } );
    await waitFor( () => expect( container.querySelector( '.vl-live-air-history-inspect' ) ).not.toBeNull() );
    const inspect = container.querySelector( '.vl-live-air-history-inspect' );
    expect( inspect?.textContent ).toMatch( /IST/ );
    expect( inspect?.textContent ).not.toMatch( /AQI \d+/ );
    expect( container.querySelector( '.vl-live-air-history-bubble' ) ).toBeNull();

    // Keyboard inspection: focusing the chart and pressing Home jumps to the oldest hour and the
    // slider announces an AQI through aria-valuetext.
    chart.focus();
    fireEvent.keyDown( chart, { key: 'Home' } );
    await waitFor( () => expect( chart.getAttribute( 'aria-valuenow' ) ).toBe( '0' ) );
    expect( chart.getAttribute( 'aria-valuetext' ) ).toMatch( /AQI \d+/ );

    // NO RED anywhere in the three new sections' markup/styles.
    expect( container.innerHTML ).not.toContain( 'dc2626' );
  } );

  it( 'does not render a "Use my location" control or trigger browser geolocation', async () => {
    // VayuLok no longer depends on browser geolocation permission; the primary location
    // interaction is city/place/pincode search. There must be no geolocation button and the
    // component must never call navigator.geolocation.
    const getCurrentPosition = vi.fn();
    vi.stubGlobal( 'navigator', { ...navigator, geolocation: { getCurrentPosition } } );
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    expect( screen.queryByRole( 'button', { name: 'Use my location' } ) ).toBeNull();
    expect( screen.queryByText( /Location permission denied/ ) ).toBeNull();
    expect( getCurrentPosition ).not.toHaveBeenCalled();
  } );

  it( 'shows IST by default and resolves selected-place local time through Google Time Zone API', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    const context = await waitFor( () => {
      const el = container.querySelector( '.vl-live-air-context' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );

    // Before/while resolution, the product contract is an explicit IST default.
    expect( context.textContent ).toMatch( /IST/ );

    await selectMumbai();

    // The component resolves local time for its initial default place (Shillong, 25.5788,91.8933)
    // AND again for the selected place, so there are TWO timezone calls. Match the one for
    // Mumbai's coordinates rather than the first call, which would be the default-place lookup.
    const tzCall = await waitFor( () => {
      const call = fetchSpy.mock.calls.find( call => {
        const url = requestUrl( call[ 0 ] as RequestInfo | URL );
        return Boolean(
          url
          && url.hostname === 'maps.googleapis.com'
          && url.pathname.startsWith( '/maps/api/timezone/json' )
          && url.searchParams.get( 'location' ) === '19.076,72.8777',
        );
      } );
      expect( call ).toBeTruthy();
      return call!;
    } );
    const tzUrl = new URL( String( tzCall[ 0 ] ) );
    expect( tzUrl.searchParams.get( 'location' ) ).toBe( '19.076,72.8777' );
    expect( Number( tzUrl.searchParams.get( 'timestamp' ) ) ).toBeGreaterThan( 0 );
    expect( tzUrl.searchParams.get( 'key' ) ).toBeTruthy();

    await waitFor( () => {
      const time = context.querySelector( '.vl-live-air-context-item.is-time' );
      expect( time?.textContent ).toContain( 'IST' );
      expect( time?.getAttribute( 'title' ) ).toContain( 'Google Time Zone API' );
    } );
  } );

  it( 'uses real 24-hour weather history and requests 96 hours of AQ forecast', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    await waitFor( () => expect(
      fetchSpy.mock.calls.some( call => requestIs( call[ 0 ] as RequestInfo | URL, 'weather.googleapis.com', '/v1/history/hours' ) ),
    ).toBe( true ) );

    const airForecastCall = await waitFor( () => {
      const call = fetchSpy.mock.calls.find( call => requestIs( call[ 0 ] as RequestInfo | URL, 'airquality.googleapis.com', '/v1/forecast' ) );
      expect( call ).toBeTruthy();
      return call!;
    } );
    const init = airForecastCall[ 1 ] as RequestInit;
    const body = JSON.parse( String( init.body ) );
    expect( body.pageSize ).toBe( 96 );
    expect( body.extraComputations ).toEqual( expect.arrayContaining( [
      'LOCAL_AQI',
      'POLLUTANT_CONCENTRATION',
      'DOMINANT_POLLUTANT_CONCENTRATION',
      'HEALTH_RECOMMENDATIONS',
      'POLLUTANT_ADDITIONAL_INFO',
    ] ) );
    const start = new Date( body.period.startTime ).getTime();
    const end = new Date( body.period.endTime ).getTime();
    // 95 hours, NOT 96: Google's forecast:lookup rejects an exactly-96-hour period with HTTP 400
    // ("time period is not supported"); 95h still returns ~96 hourly rows. Requesting 96h was the
    // cause of the forecast rendering empty in production.
    expect( Math.round( ( end - start ) / 3_600_000 ) ).toBe( 95 );
  } );

  it( 'requests the India CPCB local AQI (customLocalAqis ind_cpcb) on the currentConditions:lookup air call', async () => {
    // INDIA API PARITY FIX. The left-card currentConditions:lookup parser prefers the India
    // CPCB index (indexes.find( i => i.code === 'ind_cpcb' )), so the request must actually ask
    // for it via customLocalAqis - matching the forecast + history calls that already do. Before
    // the fix this body was MISSING customLocalAqis, so ind_cpcb never came back and the parser
    // silently fell to uaqi.
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    const airLookupCall = await waitFor( () => {
      const call = fetchSpy.mock.calls.find( call =>
        requestIs( call[ 0 ] as RequestInfo | URL, 'airquality.googleapis.com', '/v1/currentConditions' )
        && Boolean( ( call[ 1 ] as RequestInit | undefined )?.body ) );
      expect( call ).toBeTruthy();
      return call!;
    } );
    const body = JSON.parse( String( ( airLookupCall[ 1 ] as RequestInit ).body ) );
    expect( body.customLocalAqis ).toEqual( [ { regionCode: 'IN', aqi: 'ind_cpcb' } ] );
    expect( body.universalAqi ).toBe( true );
    expect( body.languageCode ).toBe( 'en' );

    // POLLUTANT_ADDITIONAL_INFO. The fetchAir selected-place call (body carries
    // location.latitude) must ask for Google's per-pollutant sources + effects so the
    // rich pollutant popover can show them. Scoped to this selected-place call only.
    const selectedPlaceCall = fetchSpy.mock.calls.find( call => {
      if ( !requestIs( call[ 0 ] as RequestInfo | URL, 'airquality.googleapis.com', '/v1/currentConditions' ) ) return false;
      const raw = ( call[ 1 ] as RequestInit | undefined )?.body;
      if ( !raw ) return false;
      const parsed = JSON.parse( String( raw ) ) as { location?: { latitude?: number } };
      return typeof parsed.location?.latitude === 'number';
    } );
    expect( selectedPlaceCall ).toBeTruthy();
    const selectedBody = JSON.parse( String( ( selectedPlaceCall![ 1 ] as RequestInit ).body ) );
    expect( selectedBody.extraComputations ).toContain( 'POLLUTANT_ADDITIONAL_INFO' );
    expect( selectedBody.extraComputations ).toContain( 'POLLUTANT_CONCENTRATION' );
  } );
  it( 'surfaces Google Air forecast ranges, 24h/7d history (no 30d) and PM2.5 heatmap tiles', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    const forecastRange = await screen.findByRole( 'group', { name: 'Air forecast range' } );
    expect( within( forecastRange ).getByRole( 'button', { name: '24h' } ) ).toHaveAttribute( 'aria-pressed', 'true' );
    fireEvent.click( within( forecastRange ).getByRole( 'button', { name: '96h' } ) );
    expect( within( forecastRange ).getByRole( 'button', { name: '96h' } ) ).toHaveAttribute( 'aria-pressed', 'true' );
    await waitFor( () => expect( container.querySelectorAll( '.vl-live-air-forecast-card' ).length ).toBe( 96 ) );
    const forecastDetail = container.querySelector( '.vl-live-air-forecast-detail' );
    expect( forecastDetail?.textContent ).toContain( 'Dominant' );
    expect( forecastDetail?.textContent ).toContain( 'Local / Universal' );
    // The general-population health advisory paragraph was removed from the forecast detail (it
    // duplicated the dedicated Health Recommendations section and broke the compact type scale).
    expect( forecastDetail?.textContent ).not.toContain( 'Forecast health recommendation.' );
    // Sources/Effects were removed from the Air Forecast detail panel; they must no longer render.
    expect( forecastDetail?.textContent ).not.toContain( 'Sources' );
    expect( forecastDetail?.textContent ).not.toContain( 'Effects' );

    // History offers only 24h and 7d now - the 30d option was removed from the UI.
    const historyRange = await screen.findByRole( 'group', { name: 'Air history range' } );
    expect( within( historyRange ).queryByRole( 'button', { name: '30d' } ) ).toBeNull();
    expect( within( historyRange ).getByRole( 'button', { name: '24h' } ) ).toBeTruthy();
    expect( within( historyRange ).getByRole( 'button', { name: '7d' } ) ).toBeTruthy();
    fireEvent.click( within( historyRange ).getByRole( 'button', { name: '24h' } ) );
    await waitFor( () => {
      const calls = fetchSpy.mock.calls.filter( call => requestIs( call[ 0 ] as RequestInfo | URL, 'airquality.googleapis.com', '/v1/history' ) );
      // No history request should ever ask for the removed 720-hour (30-day) window.
      const has720 = calls.some( call => {
        const raw = ( call[ 1 ] as RequestInit | undefined )?.body;
        return raw ? JSON.parse( String( raw ) ).hours === 720 : false;
      } );
      expect( has720 ).toBe( false );
      const has24 = calls.some( call => {
        const raw = ( call[ 1 ] as RequestInit | undefined )?.body;
        return raw ? JSON.parse( String( raw ) ).hours === 24 : false;
      } );
      expect( has24 ).toBe( true );
    } );

    const metric = await screen.findByRole( 'group', { name: 'Heatmap metric' } );
    fireEvent.click( within( metric ).getByRole( 'button', { name: 'PM2.5' } ) );
    await waitFor( () => {
      const pm25 = rec.imageMapTypeOpts.find( opts => {
        const get = opts.getTileUrl as ( ( coord: { x: number; y: number }, zoom: number ) => string ) | undefined;
        return typeof get === 'function' && get( { x: 1, y: 2 }, 5 ).includes( 'mapTypes/PM25_INDIGO_PERSIAN/heatmapTiles' );
      } );
      expect( pm25 ).toBeTruthy();
    } );
    expect( container.querySelector( '.vl-live-air-heatmap-legend.is-pm25' )?.textContent ).toContain( 'Higher' );
    expect( container.querySelector( '.vl-live-air-heatmap-legend.is-pm25' )?.textContent ).toContain( 'Lower' );
  } );

  it( 'shows an Air Forecast error state when forecast:lookup fails, without hiding the failure', async () => {
    // environmentFetch but forecast:lookup returns HTTP 500 - the section must surface a concise
    // fallback, not silently render nothing.
    const base = environmentFetch();
    const failingForecast = vi.fn( ( input: RequestInfo | URL, init?: RequestInit ) => {
      if ( requestIs( input, 'airquality.googleapis.com', '/v1/forecast' ) ) {
        return Promise.resolve( { ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ( {} ) } as Response );
      }
      return base( input, init );
    } );
    vi.stubGlobal( 'fetch', failingForecast );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    await waitFor( () => {
      const forecast = container.querySelector( '.vl-live-air-forecast' );
      expect( forecast?.textContent ).toContain( 'Air forecast is temporarily unavailable.' );
    } );
    // No forecast cards rendered on the error path.
    expect( container.querySelectorAll( '.vl-live-air-forecast-card:not(.is-skeleton)' ).length ).toBe( 0 );
  } );

  it( 'shows an Air Forecast empty state when Google returns no forecast rows', async () => {
    const base = environmentFetch();
    const emptyForecast = vi.fn( ( input: RequestInfo | URL, init?: RequestInit ) => {
      if ( requestIs( input, 'airquality.googleapis.com', '/v1/forecast' ) ) {
        return Promise.resolve( { ok: true, status: 200, json: async () => ( { hourlyForecasts: [] } ) } as Response );
      }
      return base( input, init );
    } );
    vi.stubGlobal( 'fetch', emptyForecast );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    await waitFor( () => {
      const forecast = container.querySelector( '.vl-live-air-forecast' );
      expect( forecast?.textContent ).toContain( 'Forecast unavailable for this location.' );
    } );
  } );

  it( 'does not visibly show "Searching worldwide…" while typing, and uses a light search focus', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    const input = await screen.findByRole( 'combobox' );
    fireEvent.change( input, { target: { value: 'Mum' } } );
    // The "Searching…" status, if present, must be the sr-only live region - never a visible
    // helper line under the field.
    await waitFor( () => {
      const live = container.querySelector( '.vl-live-sr-only[role="status"]' );
      const visibleStatus = container.querySelector( '.vl-live-search-status' );
      // Either searching is announced sr-only, or it is already resolved; a visible
      // "Searching worldwide…" line must never appear.
      expect( visibleStatus?.textContent || '' ).not.toContain( 'Searching worldwide' );
      void live;
    } );

    // Result rows carry a leading location icon and the hover/selected lime treatment.
    const option = await screen.findByRole( 'option', { name: /Mumbai/i } );
    expect( option.querySelector( '.vl-live-search-result-icon' ) ).not.toBeNull();
  } );

  it( 'does not force India CPCB custom AQI on non-India destinations', async () => {
    rec = installGoogleMaps( { placeCountryCode: 'BD' } );
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    const selectedPlaceCall = await waitFor( () => {
      const call = fetchSpy.mock.calls.find( call => {
        if ( !requestIs( call[ 0 ] as RequestInfo | URL, 'airquality.googleapis.com', '/v1/currentConditions' ) ) return false;
        const raw = ( call[ 1 ] as RequestInit | undefined )?.body;
        if ( !raw ) return false;
        const parsed = JSON.parse( String( raw ) );
        return parsed.location?.latitude === 19.076;
      } );
      expect( call ).toBeTruthy();
      return call!;
    } );
    const body = JSON.parse( String( ( selectedPlaceCall[ 1 ] as RequestInit ).body ) );
    expect( body.universalAqi ).toBe( true );
    expect( body.extraComputations ).toContain( 'LOCAL_AQI' );
    expect( body.customLocalAqis ).toBeUndefined();
  } );

  it( 'fires the place autocomplete on the fast 120ms debounce - not immediately, and not on the old 300ms lag', async () => {
    // PINS "auto-complete should work very quickly". The component debounces the Autocomplete
    // Data API request by SEARCH_DEBOUNCE_MS (120ms): one request per settled keystroke, but
    // snappy. This test asserts the actual TIMING via fake timers so a regression back to the
    // old 300ms value FAILS CI (the request would not have fired by ~120ms), and removing the
    // debounce entirely ALSO fails (the request would fire before the sub-threshold advance).
    //
    // The initial map-ready phase relies on requestAnimationFrame (tilesloaded) + awaited
    // importLibrary + waitFor, which are fragile under fake timers, so we drive map-ready on
    // REAL timers and only switch to fake timers around the debounce window. runSearch is async
    // (it awaits ensurePlacesLibrary -> importLibrary('places') before calling
    // fetchAutocompleteSuggestions), so we advance with advanceTimersByTimeAsync to flush both
    // the debounce timer AND the awaited autocomplete promise chain.
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );

    // Map-ready boundary on real timers: the combobox renders only after tilesloaded flips mapReady.
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    const input = await screen.findByRole( 'combobox' );

    // Fresh recorder slate, then switch to fake timers for the debounce window only.
    rec.autocompleteCalls.length = 0;
    vi.useFakeTimers();
    try {
      fireEvent.change( input, { target: { value: 'Mumbai' } } );

      // Immediately after the keystroke the debounce timer is still pending: no request yet.
      expect( rec.autocompleteCalls ).toHaveLength( 0 );

      // Just UNDER the 120ms threshold the request must STILL not have fired. If the debounce
      // were removed, a request would already be queued here; if it were present but 120ms,
      // 100ms is not enough to cross it.
      await vi.advanceTimersByTimeAsync( 100 );
      expect( rec.autocompleteCalls ).toHaveLength( 0 );

      // Shortly after crossing 120ms the request fires. The extra advance also flushes the
      // awaited importLibrary('places') + fetchAutocompleteSuggestions microtasks so the call
      // is recorded. A 300ms debounce would NOT have fired by this point, failing the test.
      await vi.advanceTimersByTimeAsync( 40 );
      expect( rec.autocompleteCalls.length ).toBeGreaterThan( 0 );
      // The request is intentionally worldwide: no India-only region or viewport restriction.
      const req = rec.autocompleteCalls.at( -1 ) || {};
      expect( req.includedRegionCodes ).toBeUndefined();
      expect( req.locationRestriction ).toBeUndefined();
      expect( req.region ).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  } );


  it( 'reopens typed autocomplete on focus and selects suggestions with pointer input', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    const input = await screen.findByRole( 'combobox' );
    fireEvent.change( input, { target: { value: 'Mumbai' } } );
    const option = await screen.findByRole( 'option', { name: /Mumbai/i } );
    expect( option ).toBeTruthy();

    // Close results, then refocus while the query remains. Focus should re-open/re-run search.
    fireEvent.keyDown( input, { key: 'Escape' } );
    expect( input.getAttribute( 'aria-expanded' ) ).toBe( 'false' );
    fireEvent.focus( input );
    await waitFor( () => expect( input.getAttribute( 'aria-expanded' ) ).toBe( 'true' ) );

    fireEvent.pointerDown( await screen.findByRole( 'option', { name: /Mumbai/i } ) );
    await waitFor( () => expect( rec.fitBoundsCalls.length ).toBeGreaterThan( 0 ) );
  } );

  it( 'does not call the unsupported India pollen endpoint, but does query weather public alerts', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();
    await waitFor( () => expect( fetchSpy.mock.calls.length ).toBeGreaterThan( 3 ) );

    // Pollen has no India coverage and is never requested.
    expect( fetchSpy.mock.calls.some( call => requestUrl( call[ 0 ] as RequestInfo | URL )?.hostname === 'pollen.googleapis.com' ) ).toBe( false );
    // publicAlerts IS queried now - coverage is per-region (India 404s, covered regions return an
    // array); the component relies on the response, not on skipping the request.
    await waitFor( () => expect( fetchSpy.mock.calls.some( call => requestIs( call[ 0 ] as RequestInfo | URL, 'weather.googleapis.com', '/v1/publicAlerts' ) ) ).toBe( true ) );
  } );

  it( 'paints the AQI heatmap and mounts the code-rendered atmosphere by default', async () => {
    const fetchSpy = airConditionsFetch( 450, 180 );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    // AQI remains a genuine Google Air Quality ImageMapType.
    await waitFor( () => {
      expect( rec.imageMapTypeOpts.length ).toBeGreaterThanOrEqual( 1 );
      expect( rec.overlayPushes.length ).toBeGreaterThanOrEqual( 1 );
    } );
    const aqiOpts = rec.imageMapTypeOpts.find( o => o.name === 'vl-live-aqi-heatmap' )!;
    expect( aqiOpts ).toBeTruthy();
    expect( aqiOpts.opacity ).toBe( 0.64 );
    const getTileUrl = aqiOpts.getTileUrl as (
      coord: { x: number; y: number }, zoom: number,
    ) => string;
    const tileUrl = getTileUrl( { x: 1, y: 2 }, 5 );
    expect( tileUrl ).toContain( 'airquality.googleapis.com' );
    expect( tileUrl ).toContain( 'mapTypes/UAQI_RED_GREEN/heatmapTiles' );
    expect( tileUrl ).toContain( '/5/1/2' );
    expect( tileUrl ).toContain( 'key=' );

    // The weather/storm appearance is now local SVG/CSS, not a fabricated Google weather tile.
    await waitFor( () => expect( container.querySelector( '.vl-live-atmosphere' ) ).not.toBeNull() );
    expect( rec.imageMapTypeOpts.some( o => o.name === 'vl-live-weather-storm' ) ).toBe( false );
    expect( rec.overlayEntries ).toHaveLength( 1 );
    expect( deckRec.overlaySetMapCalls.some( value => Boolean( value ) ) ).toBe( false );
  } );

  it( 'keeps the SVG/CSS atmosphere on the live map without a separate Storm switch', async () => {
    vi.stubGlobal( 'fetch', airConditionsFetch( 450, 180 ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    await waitFor( () => expect( container.querySelector( '.vl-live-atmosphere' ) ).not.toBeNull() );
    expect( screen.queryByRole( 'switch', { name: 'Weather storm overlay' } ) ).toBeNull();
  } );

  it( 'does not render the removed map layer or selected-location pills', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    expect( container.querySelector( '.vl-live-layers' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-selected-label' ) ).toBeNull();
  } );

  it( 'requests address descriptors but never invents descriptor or elevation text', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    await waitFor( () => expect(
      rec.geocodeCalls.some( call => Array.isArray( call.extraComputations ) && ( call.extraComputations as unknown[] ).includes( 'ADDRESS_DESCRIPTORS' ) ),
    ).toBe( true ) );
    expect( container.querySelector( '.vl-live-descriptor-line' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-place-facts' ) ).toBeNull();
  } );
} );

describe( 'VayuLokLive v8 no-key map fallback', () => {
  it( 'shows a map-free keyless fallback without injecting Maps JS or issuing environmental calls', async () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', '' );
    const fetchSpy = vi.fn();
    vi.stubGlobal( 'fetch', fetchSpy );
    // Seed the Google Maps stub anyway so we can PROVE the keyless path never touches it:
    // with no key the component must inject no Maps JS and construct no ImageMapType, so this
    // recorder must stay empty even though window.google.maps is available.
    const rec = installGoogleMaps();
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );

    expect( document.getElementById( 'gmaps-js' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-map-canvas' ) ).toBeNull();
    // THE PRIVACY CONTRACT. The keyless path used to render an eager
    // maps.google.com/...&output=embed iframe - a third-party request on a public page
    // that no visitor consented to. It is gone, and nothing on this path may reach any
    // Google host: not an iframe, not an img, not a link, not a remote background.
    expect( container.querySelector( '.vl-live-map-embed' ) ).toBeNull();
    expect( container.querySelector( 'iframe' ) ).toBeNull();
    const remoteRefs = Array.from( container.querySelectorAll( '[src],[href],[srcset],[data-src]' ) )
      .flatMap( el => [ 'src', 'href', 'srcset', 'data-src' ].map( a => el.getAttribute( a ) || '' ) );
    expect( remoteRefs.some( value => /google/i.test( value ) ) ).toBe( false );
    expect( container.innerHTML ).not.toContain( 'maps.google.com' );
    expect( container.innerHTML ).not.toContain( 'output=embed' );

    // And the map-free placeholder IS what renders instead, carrying only place state
    // the component already holds.
    const placeholder = container.querySelector( '.vl-live-map-placeholder' );
    expect( placeholder ).not.toBeNull();
    expect( placeholder?.tagName ).toBe( 'DIV' );
    expect( placeholder?.textContent ).toContain( 'Shillong' );
    expect( placeholder?.textContent ).toContain( 'Interactive map unavailable' );

    // HONEST DEGRADATION for the three new Air sections. Without a key `air` is null, so the
    // heatmap toggle, the Health Recommendations tablist and the Hourly History chart live
    // content are all absent - no fabricated chart, no fake persona panel, zero fetches.
    expect( screen.queryByRole( 'switch', { name: 'Air quality heatmap' } ) ).toBeNull();
    // Storm is part of the map atmosphere now; there is intentionally no Storm switch.
    expect( screen.queryByRole( 'switch', { name: 'Weather storm overlay' } ) ).toBeNull();
    expect( screen.queryByRole( 'tablist', { name: 'Health recommendation profiles' } ) ).toBeNull();
    expect( container.querySelector( '.vl-live-air-history-chart' ) ).toBeNull();

    // DEFAULT-ON MUST NOT FIRE WITHOUT A KEY. The AQI tile overlay must construct no
    // google.maps.ImageMapType and the SVG atmosphere must not mount because the keyed map
    // never becomes ready.
    expect( rec.imageMapTypeOpts ).toHaveLength( 0 );
    expect( rec.overlayPushes ).toHaveLength( 0 );
    expect( rec.overlayEntries ).toHaveLength( 0 );
    expect( container.textContent ).not.toContain( 'Health Recommendations' );
    expect( container.textContent ).not.toContain( 'Hourly History' );

    // Subscribe, Contribute and Share were deliberately removed from the Air card.
    expect( container.querySelector( '.vl-live-air-extras' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-air-subscribe' ) ).toBeNull();
    expect( container.querySelector( 'section.bc.is-embedded' ) ).toBeNull();
    expect( container.querySelector( '[aria-label="Share this page on WhatsApp"]' ) ).toBeNull();

    // No live pollutant tooltip can exist without live Air data.
    expect( container.querySelector( '.vl-live-air-pollutant-pop' ) ).toBeNull();

    expect( fetchSpy ).not.toHaveBeenCalled();
    expect( container.textContent ).not.toContain( 'Live air quality and weather' );
    expect( container.textContent ).not.toContain( 'Selected place' );
    expect( container.textContent ).not.toContain( 'Search India to see live weather and air.' );
  } );

  it( 'renders the callout card shape and the exact Header search-field idiom', async () => {
    // CSS assertions read the rendered <style> text: vitest renders styled-jsx as a plain,
    // unscoped <style>, so the component's whole stylesheet is readable as text. Formatting is
    // the component's single-line declaration style, so these match on the exact declarations.
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', '' );
    vi.stubGlobal( 'fetch', vi.fn() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );

    const css = Array.from( container.querySelectorAll( 'style' ) ).map( s => s.textContent || '' ).join( '\n' );

    // MAP SHELL stays full-bleed. The Air card is a wider, lighter inspector with no
    // decorative callout tail/modal pointer.
    const shellRule = css.match( /\.vl-live-map-shell\{[^}]*\}/ )?.[ 0 ] || '';
    expect( shellRule ).toContain( 'overflow:visible' );
    expect( shellRule ).toContain( 'isolation:isolate' );
    expect( shellRule ).toContain( 'height:auto' );
    const cardWrapRule = css.match( /\.vl-live-air-card-wrap\{[^}]*\}/ )?.[ 0 ] || '';
    expect( cardWrapRule ).toContain( 'width:min(416px,calc(100% - 32px))' );
    expect( cardWrapRule ).toContain( 'drop-shadow(0 8px 18px rgba(26,58,42,.10))' );
    expect( css ).not.toContain( '.vl-live-air-card-wrap::after{' );

    // GLOBAL SEARCH FIELD: the outer wrapper is visually absent. The input itself reuses
    // Header .nav-search / ProductBlogPanel .pbp-search: transparent, bottom hairline only.
    expect( container.querySelector( '.vl-live-search-field svg' ) ).toBeNull();
    const inputRule = css.match( /\.vl-live-search-field input\{[^}]*\}/ )?.[ 0 ] || '';
    expect( inputRule ).toContain( 'border-bottom:1px solid #e5e7eb' );
    expect( inputRule ).toContain( 'border:0' );
    expect( inputRule ).toContain( 'font-size:16px' );
    expect( inputRule ).toContain( 'font-weight:400' );
    expect( inputRule ).toContain( 'background:transparent' );
    // LIGHT focus treatment: a thin dark-green bottom border + a subtle lime accent line, NOT a
    // heavy rectangular outline around the whole field.
    const inputFocus = css.match( /\.vl-live-search-field input:focus-visible\{[^}]*\}/ )?.[ 0 ] || '';
    expect( inputFocus ).toContain( 'border-bottom-color:#1a3a2a' );
    expect( inputFocus ).toContain( '0 1px 0 0 var(--lime)' );
    expect( inputFocus ).toContain( 'outline:none' );
    expect( inputFocus ).not.toContain( 'outline:3px' );
    const fieldRule = css.match( /\.vl-live-search-field\{[^}]*\}/ )?.[ 0 ] || '';
    expect( fieldRule ).toContain( 'border-radius:0' );
    // DECOUPLED FROM mapReady: the search box now renders on EVERY path (it no longer waits for
    // the map to paint), so a user can search for a city/pincode even on the keyless path or if
    // the map fails. The live #vl-live-search input is therefore present here.
    const searchInput = container.querySelector( '#vl-live-search' ) as HTMLInputElement | null;
    expect( searchInput ).not.toBeNull();
    expect( searchInput?.getAttribute( 'placeholder' ) ).toBe( 'Search a city or pincode' );
    expect( css ).toContain( '.vl-live-search-field input::-webkit-search-cancel-button' );
    expect( css ).toContain( '-webkit-appearance:none' );
    expect( css ).toContain( '.vl-live-search-field input::-ms-clear{display:none' );
    const searchWrapRule = css.match( /\.vl-live-map-search\{[^}]*\}/ )?.[ 0 ] || '';
    expect( searchWrapRule ).toContain( 'width:min(760px,calc(100% - 48px))' );
    expect( searchWrapRule ).toContain( 'margin:14px auto 20px' );
    expect( searchWrapRule ).toContain( 'padding:0' );
    expect( searchWrapRule ).toContain( 'background:transparent' );
    expect( searchWrapRule ).toContain( 'border:0' );
    expect( searchWrapRule ).toContain( 'border-radius:0' );
    expect( searchWrapRule ).toContain( 'box-shadow:none' );
    expect( searchWrapRule ).toContain( 'z-index:30' );
    expect( searchWrapRule ).not.toContain( 'grid-area:1/1' );

    // The map region, shell AND the search surface now render on every path - search is no longer
    // gated on mapReady, so it is usable while the map loads or if it fails.
    const searchSurface = container.querySelector( '.vl-live-map-search' );
    const mapRegion = container.querySelector( '.vl-live-map-region' );
    const mapMain = container.querySelector( '.vl-live-shell' );
    expect( searchSurface ).not.toBeNull();
    expect( mapRegion ).not.toBeNull();
    expect( mapMain ).not.toBeNull();

    // Pollutant info control follows the SupportWidget WhatsApp skin exactly:
    // lime surface, deep-green icon, lighter-lime hover, circular shape.
    const infoRule = cssRuleFor( css, '.vl-live-air-pollutant-info' );
    expect( infoRule ).toContain( 'background:var(--lime)' );
    expect( infoRule ).toContain( 'color:var(--green)' );
    expect( infoRule ).toContain( 'border-radius:50%' );
    const infoHoverRule = cssRuleFor( css, '.vl-live-air-pollutant-info:hover' );
    expect( infoHoverRule ).toContain( 'background:var(--lime-hover)' );
    expect( infoHoverRule ).toContain( 'color:var(--green)' );
    expect( css ).toContain( '.vl-live-air-health-tabs{scroll-snap-type:x mandatory' );
    expect( css ).toContain( '.vl-live-air-health-tab{scroll-snap-align:start}' );
    const moreRule = css.match( /\.vl-live-air-health-more\{[^}]*\}/ )?.[ 0 ] || '';
    const moreHoverRule = css.match( /\.vl-live-air-health-more:hover\{[^}]*\}/ )?.[ 0 ] || '';
    expect( moreRule ).toContain( 'text-decoration:none' );
    expect( moreHoverRule ).toContain( 'text-decoration:underline' );

    // One UI-system pass: section headings share the homepage card-heading token and one
    // lime accent; pollutant names are real content (17px), not metadata-sized copy.
    // These section headings and section wrappers share one grouped rule each. The group gained
    // .vl-live-air-forecast(-title) when the Air Forecast section landed, so a hardcoded
    // selector-list regex no longer matches; look the rule up by membership of one representative
    // selector instead, which stays correct as the group grows.
    const sectionTitleRule = cssRuleFor( css, '.vl-live-air-pollutants-title' );
    expect( sectionTitleRule ).toContain( 'font-size:var(--vl-card-heading-size)' );
    expect( sectionTitleRule ).toContain( 'border-left:3px solid var(--lime)' );
    const sectionRule = cssRuleFor( css, '.vl-live-air-pollutants' );
    expect( sectionRule ).toContain( 'margin-top:var(--vl-section-gap)' );
    expect( sectionRule ).toContain( 'padding-top:var(--vl-section-pad)' );
    expect( css ).not.toContain( '.vl-live-air-pollutants-title::before' );
    const pollutantLabelRule = css.match( /\.vl-live-air-pollutant-label\{[^}]*\}/ )?.[ 0 ] || '';
    expect( pollutantLabelRule ).toContain( 'font-size:17px' );
    const pollutantRowRule = css.match( /\.vl-live-air-pollutant-row\{[^}]*\}/ )?.[ 0 ] || '';
    expect( pollutantRowRule ).toContain( 'grid-template-columns:minmax(0,1fr) minmax(118px,auto) var(--vl-action-size)' );
    const pollutantValueRule = css.match( /\.vl-live-air-pollutant-value\{[^}]*\}/ )?.[ 0 ] || '';
    expect( pollutantValueRule ).toContain( 'min-width:118px' );
    expect( pollutantValueRule ).toContain( 'text-align:right' );
    expect( pollutantValueRule ).toContain( 'font-variant-numeric:tabular-nums' );
    // The heatmap On/Off state control lives in the air panel's `air ? (...)` branch, so on the
    // keyless path (no live air data) it is correctly absent. Assert that absence rather than a
    // live On/Off string, which this path can never produce.
    expect( container.querySelector( '.vl-live-air-heatmap-state' ) ).toBeNull();
    const aqiSpineRule = css.match( /\.vl-live-air-aqi-spine\{[^}]*\}/ )?.[ 0 ] || '';
    expect( aqiSpineRule ).toContain( '#3da35a' );
    expect( aqiSpineRule ).toContain( '#2563eb' );
    expect( aqiSpineRule ).toContain( '#9849e8' );
    expect( css ).not.toContain( '.vl-live-air-gauge-arc{' );
    expect( css ).not.toContain( '.vl-live-air-gauge-track{' );

    // The duplicate top "Air Quality Details" heading is gone on every path. The live
    // "Pollutants" section only renders in the air panel's `air ? (...)` branch, so on this
    // keyless path - consistent with the "Hourly History"/"Health Recommendations" absences
    // asserted earlier in this test - it is replaced by the honest empty state rather than a
    // live pollutant list.
    expect( container.textContent ).not.toContain( 'Air Quality Details' );
    expect( container.textContent ).not.toContain( 'Pollutants' );
    expect( container.querySelector( '.vl-live-air-empty' )?.textContent )
      .toContain( 'Live air quality appears here once a place is selected.' );
  } );
} );
