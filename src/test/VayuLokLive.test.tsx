import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

/* ---------------------------------------------------------------------------------------
   deck.gl DYNAMIC-IMPORT MOCKS (FEAT-002)
   ---------------------------------------------------------------------------------------
   The component imports the deck.gl overlay + scatter layer DYNAMICALLY, inside the
   layer-activation effect:
       const { GoogleMapsOverlay } = await import( '@deck.gl/google-maps' );
       const { ScatterplotLayer }  = await import( '@deck.gl/layers' );
   so they stay out of SSR / the initial bundle and are NEVER loaded on the no-key
   honest-degradation path. These vi.mock factories replace both packages with fakes that
   RECORD what the component does: which map the overlay is attached to (setMap), what
   layers it is given (setProps), and the props each ScatterplotLayer receives (so a test
   can read back the fill colours and the real point data). vi.mock is hoisted and survives
   vi.resetModules(), so every freshly re-imported component instance gets these fakes. The
   shared recorder is created with vi.hoisted so the factory may reference it safely. */
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

async function selectMumbai() {
  const input = await screen.findByRole( 'combobox' );
  fireEvent.change( input, { target: { value: 'Mumbai' } } );
  fireEvent.mouseDown( await screen.findByRole( 'option', { name: /Mumbai/i } ) );
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
          indexes: [ { code: 'ind_cpcb', aqi: 74, category: 'Satisfactory', dominantPollutant: 'pm25' } ],
          pollutants: [
            { code: 'pm25', concentration: { value: 28, units: 'MICROGRAMS_PER_CUBIC_METER' }, additionalInfo: { sources: 'Combustion of fuels in vehicles, power plants and industry.', effects: 'Penetrates deep into lungs and can trigger respiratory and cardiovascular problems.' } },
            { code: 'pm10', concentration: { value: 44, units: 'MICROGRAMS_PER_CUBIC_METER' } },
          ],
          healthRecommendations: { generalPopulation: 'Normal outdoor activity is suitable for most people.' },
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
            indexes: [ { code: 'ind_cpcb', aqi: 70 + i } ],
            pollutants: [ { code: 'pm25', concentration: { value: 25 + i, units: 'MICROGRAMS_PER_CUBIC_METER' } } ],
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
  let rec: MapsRecorder;

  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
    rec = installGoogleMaps();
  } );

  it( 'loads a draggable global hybrid map and omits the removed map pills', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    expect( rec.mapOpts?.restriction ).toBeUndefined();
    expect( rec.mapOpts?.center ).toEqual( { lat: 25, lng: 86 } );
    expect( rec.mapOpts?.zoom ).toBe( 4 );
    expect( rec.mapOpts?.mapTypeId ).toBe( 'hybrid' );
    expect( rec.mapOpts?.gestureHandling ).toBe( 'greedy' );
    expect( rec.mapOpts?.draggable ).toBe( true );
    expect( rec.mapOpts?.scrollwheel ).toBe( true );
    expect( rec.mapOpts?.disableDoubleClickZoom ).toBe( false );
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
    expect( decodeURIComponent( String( icon ) ) ).toContain( '#1a3a2a' );
    expect( decodeURIComponent( String( icon ) ) ).toContain( '#d1f470' );
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
    expect( card.querySelector( '.vl-live-air-card-title' )?.textContent ).toBe( 'Air Quality Details' );

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

  it( 'shows the circular AQI gauge, category word, dominant chip and pollutant rows in the floating card, and a Weather placeholder on toggle', async () => {
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

    // Gauge: the parsed AQI number is centred, the category WORD carries severity (not
    // colour alone), and the SVG arc uses a no-red brand stroke.
    expect( panel.querySelector( '.vl-live-air-gauge-value' )?.textContent ).toBe( '74' );
    expect( panel.querySelector( '.vl-live-air-gauge-word' )?.textContent ).toContain( 'Satisfactory' );
    const arc = panel.querySelector( '.vl-live-air-sev-sat .vl-live-air-gauge-arc' );
    expect( arc ).not.toBeNull();
    // The dominant-pollutant chip reads the friendly label (PM2.5), matching the
    // pollutant rows, rather than the raw Google code (pm25).
    const dominantChip = panel.querySelector( '.vl-live-air-dominant' );
    expect( dominantChip?.textContent ).toContain( 'PM2.5' );
    expect( dominantChip?.textContent ).not.toContain( 'pm25' );

    // At least one pollutant row with value + unit + label + info icon.
    const rows = panel.querySelectorAll( '.vl-live-air-pollutant-row' );
    expect( rows.length ).toBeGreaterThan( 0 );
    const firstRow = rows[ 0 ];
    expect( firstRow.querySelector( '.vl-live-air-pollutant-value' )?.textContent ).toMatch( /\d/ );
    expect( firstRow.querySelector( '.vl-live-air-pollutant-label' )?.textContent?.length ).toBeGreaterThan( 0 );
    const info = firstRow.querySelector( '.vl-live-air-pollutant-info' );
    expect( info ).not.toBeNull();

    // The pollutant info exposes its text via a CUSTOM tooltip wired with aria-describedby
    // (keyboard reachable), NOT the native title= attribute.
    expect( info?.hasAttribute( 'title' ) ).toBe( false );
    expect( info?.getAttribute( 'tabindex' ) ).toBe( '0' );
    const describedBy = info?.getAttribute( 'aria-describedby' );
    expect( describedBy ).toBeTruthy();
    const tip = firstRow.querySelector( `#${describedBy}` );
    expect( tip ).not.toBeNull();
    expect( tip?.getAttribute( 'role' ) ).toBe( 'tooltip' );

    // RICH POPOVER: the pm25 row (dominant pollutant, first row) carries Google's
    // per-pollutant sources + effects. The popover shows the pollutant NAME heading plus
    // the 'Sources:' and 'Effects:' subheadings with the exact API-supplied text. The
    // descriptions come ONLY from the mocked additionalInfo (never fabricated).
    const pm25Row = Array.from( rows ).find(
      r => ( r.querySelector( '.vl-live-air-pollutant-label' )?.textContent ?? '' ).includes( 'PM2.5' )
    ) as HTMLElement;
    expect( pm25Row ).toBeTruthy();
    const pm25Describe = pm25Row.querySelector( '.vl-live-air-pollutant-info' )?.getAttribute( 'aria-describedby' );
    const pm25Tip = pm25Row.querySelector( `#${pm25Describe}` );
    expect( pm25Tip ).not.toBeNull();
    expect( pm25Tip?.getAttribute( 'role' ) ).toBe( 'tooltip' );
    expect( pm25Tip?.textContent ).toContain( 'PM2.5' );
    expect( pm25Tip?.textContent ).toContain( 'Sources:' );
    expect( pm25Tip?.textContent ).toContain( 'Combustion of fuels in vehicles, power plants and industry.' );
    expect( pm25Tip?.textContent ).toContain( 'Effects:' );
    expect( pm25Tip?.textContent ).toContain( 'Penetrates deep into lungs and can trigger respiratory and cardiovascular problems.' );

    // The pm10 row has no additionalInfo in the mock, so it falls back to the value+unit
    // line and renders NO 'Sources:'/'Effects:' heading (honest degradation per row).
    const pm10Row = Array.from( rows ).find(
      r => ( r.querySelector( '.vl-live-air-pollutant-label' )?.textContent ?? '' ).includes( 'PM10' )
    ) as HTMLElement;
    expect( pm10Row ).toBeTruthy();
    const pm10Describe = pm10Row.querySelector( '.vl-live-air-pollutant-info' )?.getAttribute( 'aria-describedby' );
    const pm10Tip = pm10Row.querySelector( `#${pm10Describe}` );
    const pm10Label = pm10Row.querySelector( '.vl-live-air-pollutant-label' )?.textContent ?? '';
    expect( pm10Tip?.textContent ).toContain( pm10Label );
    expect( pm10Tip?.textContent ).toMatch( /\d/ );
    expect( pm10Tip?.textContent ).not.toContain( 'Sources:' );
    expect( pm10Tip?.textContent ).not.toContain( 'Effects:' );

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
    expect( weatherPanel?.textContent ).toMatch( /coming soon/i );
    // The Air panel is no longer shown while Weather is selected.
    expect( container.querySelector( '[aria-label="Air details"]' ) ).toBeNull();
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

    // (1) HEATMAP. An accessible on/off switch that is ON BY DEFAULT and drives the
    //     continuous Google Air Quality TILE overlay path (default-on, FEAT-001), plus a
    //     Poor/Excellent legend. There are now TWO role=switch controls in the Air panel
    //     (Air quality heatmap + Weather storm overlay), so the heatmap switch is addressed
    //     by its accessible name, not by position.
    const heatSwitch = await screen.findByRole( 'switch', { name: 'Air quality heatmap' } );
    expect( heatSwitch ).toHaveAttribute( 'aria-checked', 'true' );
    expect( heatSwitch ).not.toBeDisabled();
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

    // (2) HEALTH RECOMMENDATIONS. A persona tablist with exactly one default-selected
    //     persona (Elderly) whose recommendation paragraph is shown; selecting another
    //     persona swaps the paragraph.
    const healthTablist = screen.getByRole( 'tablist', { name: 'Health recommendation profiles' } );
    const personaTabs = healthTablist.querySelectorAll( '[role="tab"]' );
    expect( personaTabs.length ).toBeGreaterThanOrEqual( 4 );
    const selected = Array.from( personaTabs ).filter( t => t.getAttribute( 'aria-selected' ) === 'true' );
    expect( selected ).toHaveLength( 1 );
    expect( selected[ 0 ].getAttribute( 'aria-label' ) ).toBe( 'Elderly' );
    // Each persona tab carries an aria-hidden Material-Symbols-style glyph (role=tab + name).
    expect( selected[ 0 ].querySelector( '.vl-live-air-health-icon' ) ).not.toBeNull();
    const healthPanel = container.querySelector( '.vl-live-air-health-panel' );
    // The Elderly copy is now short & crisp; assert a NON-EMPTY paragraph with a stable word.
    const elderlyText = healthPanel?.querySelector( '.vl-live-air-health-text' )?.textContent ?? '';
    expect( elderlyText.length ).toBeGreaterThan( 0 );
    expect( elderlyText ).toContain( 'short of breath' );

    const generalTab = screen.getByRole( 'tab', { name: 'General population' } );
    fireEvent.click( generalTab );
    await waitFor( () => expect( generalTab ).toHaveAttribute( 'aria-selected', 'true' ) );
    // Selecting General swaps the paragraph to a DIFFERENT non-empty short copy.
    const generalText = healthPanel?.querySelector( '.vl-live-air-health-text' )?.textContent ?? '';
    expect( generalText.length ).toBeGreaterThan( 0 );
    expect( generalText ).not.toBe( elderlyText );
    expect( generalText ).toContain( 'fine for most people' );

    // (3) HOURLY HISTORY. Title + a UTC timestamp derived from real data + a role=img chart
    //     with an aria-label mentioning the current value and a visible current-value marker.
    expect( screen.getByText( 'Hourly History' ) ).toBeTruthy();
    const chart = await waitFor( () => {
      const el = container.querySelector( '.vl-live-air-history-chart' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( chart.getAttribute( 'role' ) ).toBe( 'img' );
    expect( chart.getAttribute( 'aria-label' ) ).toMatch( /AQI history/ );
    expect( chart.getAttribute( 'aria-label' ) ).toMatch( /current 72/ );
    expect( container.querySelector( '.vl-live-air-history-stamp' )?.textContent ).toMatch( /UTC/ );
    expect( container.querySelector( '.vl-live-air-history-bubble' )?.textContent ).toBe( '72' );

    // NO RED anywhere in the three new sections' markup/styles.
    expect( container.innerHTML ).not.toContain( 'dc2626' );
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
    const start = new Date( body.period.startTime ).getTime();
    const end = new Date( body.period.endTime ).getTime();
    expect( Math.round( ( end - start ) / 3_600_000 ) ).toBe( 96 );
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

  it( 'does not call unsupported India pollen or Google weather-alert endpoints', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();
    await waitFor( () => expect( fetchSpy.mock.calls.length ).toBeGreaterThan( 3 ) );

    expect( fetchSpy.mock.calls.some( call => requestUrl( call[ 0 ] as RequestInfo | URL )?.hostname === 'pollen.googleapis.com' ) ).toBe( false );
    expect( fetchSpy.mock.calls.some( call => requestIs( call[ 0 ] as RequestInfo | URL, 'weather.googleapis.com', '/v1/publicAlerts' ) ) ).toBe( false );
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

  it( 'toggles the independent SVG/CSS atmosphere with the Weather storm switch', async () => {
    const fetchSpy = airConditionsFetch( 450, 180 );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    await waitFor( () => {
      expect( container.querySelector( '[aria-label="Air details"]' ) ).not.toBeNull();
      expect( container.querySelector( '.vl-live-atmosphere' ) ).not.toBeNull();
    } );

    const stormSwitch = await screen.findByRole( 'switch', { name: 'Weather storm overlay' } );
    expect( stormSwitch ).toHaveAttribute( 'aria-checked', 'true' );
    expect( stormSwitch ).not.toBeDisabled();

    fireEvent.click( stormSwitch );
    await waitFor( () => {
      expect( stormSwitch ).toHaveAttribute( 'aria-checked', 'false' );
      expect( container.querySelector( '.vl-live-atmosphere' ) ).toBeNull();
    } );

    fireEvent.click( stormSwitch );
    await waitFor( () => {
      expect( stormSwitch ).toHaveAttribute( 'aria-checked', 'true' );
      expect( container.querySelector( '.vl-live-atmosphere' ) ).not.toBeNull();
    } );
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
    expect( placeholder?.textContent ).toContain( 'Lumpyngngad' );
    expect( placeholder?.textContent ).toContain( 'Interactive map unavailable' );

    // HONEST DEGRADATION for the three new Air sections. Without a key `air` is null, so the
    // heatmap toggle, the Health Recommendations tablist and the Hourly History chart live
    // content are all absent - no fabricated chart, no fake persona panel, zero fetches.
    expect( screen.queryByRole( 'switch', { name: 'Air quality heatmap' } ) ).toBeNull();
    // The new Weather storm switch is likewise absent on the keyless path.
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

    // PAGE FURNITURE renders on EVERY path, including keyless: Subscribe, Contribute and Share
    // are embedded INSIDE the floating Air card (they are furniture, not live data). They are
    // SSR/keyless safe and must fire NO network call on mount, which is what the fetch assertion
    // below proves now that they are mounted here.
    const extras = container.querySelector( '.vl-live-air-card .vl-live-air-extras' );
    expect( extras ).not.toBeNull();
    // SUBSCRIBE now matches the LIVE blog post: a compact lime WhatsApp pill, NOT the old
    // in-page BlogSubscribe signup form. It is a static anchor at the shared Subscribe deep link
    // with the 'Continue on WhatsApp' microcopy below it, the twin of the Contribute pill. The
    // old form's section ([aria-labelledby="blog-subscribe-title"], 'Get new posts directly') is
    // gone, so neither must appear here.
    const subscribe = extras?.querySelector( 'a.vl-live-air-subscribe' );
    expect( subscribe ).not.toBeNull();
    expect( subscribe?.getAttribute( 'href' ) ).toBe( 'https://wa.me/message/WUDPTMYSO6XII1' );
    expect( subscribe?.getAttribute( 'aria-label' ) ).toBe( 'Subscribe on WhatsApp' );
    expect( subscribe?.textContent ).toContain( 'Subscribe' );
    expect( extras?.querySelector( '[aria-labelledby="blog-subscribe-title"]' ) ).toBeNull();
    expect( extras?.textContent ).not.toContain( 'Get new posts directly' );
    expect( extras?.textContent ).toContain( 'Continue on WhatsApp' );
    // BlogContribution's embedded section (plain WhatsApp anchor, no fetch), its Contribute pill
    // pointing at the DISTINCT Contribute deep link.
    expect( extras?.querySelector( 'section.bc.is-embedded' ) ).not.toBeNull();
    expect( extras?.textContent ).toContain( 'Contribute' );
    const contribute = extras?.querySelector( 'a.bc-cta' );
    expect( contribute?.getAttribute( 'href' ) ).toBe( 'https://wa.me/message/BYFLCAAMSZBXD1' );
    // ShareLinks' WhatsApp control, pointing at the absolute /vayulok/ page URL.
    const shareWa = extras?.querySelector( 'a[aria-label="Share this page on WhatsApp"]' );
    expect( shareWa ).not.toBeNull();
    const shareHref = shareWa?.getAttribute( 'href' ) || '';
    // The url is unchanged - the share link still resolves to the live /vayulok/ tool.
    expect( shareHref ).toContain( 'wecare.digital%2Fvayulok%2F' );
    // HONEST SHARE TITLE on the keyless path. air === null and weather === null here, so the
    // composed title degrades to the selected place name (DEFAULT_PLACE 'Lumpyngngad') plus the
    // neutral VayuLok tail - it fabricates NO AQI or weather numbers. The whole message
    // (title + url) is URL-encoded into the WhatsApp href, so decode it and assert on the title.
    const sharePrefix = 'https://api.whatsapp.com/send?text=';
    expect( shareHref.startsWith( sharePrefix ) ).toBe( true );
    const shareMessage = decodeURIComponent( shareHref.slice( sharePrefix.length ) );
    expect( shareMessage ).toContain( 'Lumpyngngad' );
    expect( shareMessage ).toContain( 'VayuLok' );
    // No fabricated live data: no AQI value, no degree reading, no NaN/undefined leak.
    expect( shareMessage ).not.toContain( 'AQI' );
    expect( shareMessage ).not.toContain( '°C' );
    expect( shareMessage ).not.toContain( 'NaN' );
    expect( shareMessage ).not.toContain( 'undefined' );

    // HONEST POLLUTANT DESCRIPTIONS. Sources/Effects text comes ONLY from Google's API
    // additionalInfo; the keyless path fires no air call, so no pollutant popover and no
    // fabricated descriptions may appear. Neither the rich Sources/Effects headings nor the
    // keyed mock's description strings leak onto this path.
    expect( container.querySelector( '.vl-live-air-pollutant-pop' ) ).toBeNull();
    expect( container.innerHTML ).not.toContain( 'Combustion of fuels in vehicles, power plants and industry.' );
    expect( container.innerHTML ).not.toContain( 'Penetrates deep into lungs and can trigger respiratory and cardiovascular problems.' );

    expect( fetchSpy ).not.toHaveBeenCalled();
    expect( container.textContent ).not.toContain( 'Live air quality and weather' );
    expect( container.textContent ).not.toContain( 'Selected place' );
    expect( container.textContent ).not.toContain( 'Search India to see live weather and air.' );
  } );

  it( 'renders the map full-bleed and the search field in the global borderless-hairline idiom', async () => {
    // CSS assertions read the rendered <style> text: vitest renders styled-jsx as a plain,
    // unscoped <style>, so the component's whole stylesheet is readable as text. Formatting is
    // the component's single-line declaration style, so these match on the exact declarations.
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', '' );
    vi.stubGlobal( 'fetch', vi.fn() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );

    const css = Array.from( container.querySelectorAll( 'style' ) ).map( s => s.textContent || '' ).join( '\n' );

    // FULL-BLEED MAP: the shell no longer carries the boxed border/border-radius, but keeps
    // overflow:hidden + isolation + the height band.
    const shellRule = css.match( /\.vl-live-map-shell\{[^}]*\}/ )?.[ 0 ] || '';
    expect( shellRule ).toContain( 'overflow:hidden' );
    expect( shellRule ).toContain( 'isolation:isolate' );
    expect( shellRule ).toContain( 'height:72dvh' );
    expect( shellRule ).not.toContain( 'border-radius' );
    expect( shellRule ).not.toMatch( /border:1px solid/ );

    // GLOBAL SEARCH IDIOM: the search input is borderless with a single bottom hairline and the
    // opaque #1a3a2a focus (var(--green)) plus the lime underline - the BlogSearch field standard.
    const inputRule = css.match( /\.vl-live-search-field input\{[^}]*\}/ )?.[ 0 ] || '';
    expect( inputRule ).toContain( 'border-bottom:1px solid var(--hair)' );
    expect( inputRule ).toContain( 'border:0' );
    const inputFocus = css.match( /\.vl-live-search-field input:focus-visible\{[^}]*\}/ )?.[ 0 ] || '';
    expect( inputFocus ).toContain( 'border-bottom-color:var(--green)' );
    expect( inputFocus ).toContain( '0 1px 0 0 #d1f470' );
    // And the old pill treatment is gone from the field container.
    const fieldRule = css.match( /\.vl-live-search-field\{[^}]*\}/ )?.[ 0 ] || '';
    expect( fieldRule ).not.toContain( 'border-radius:var(--pill-r)' );
  } );
} );

describe( 'composeVayuLokShareTitle - honest, data-driven Share title', () => {
  // Pure module-level helper. Loaded fresh so it is read after any env stubbing, matching the
  // dynamic-import discipline the rest of this suite uses for the component module.
  async function loadCompose() {
    vi.resetModules();
    const mod = await import( '../components/VayuLokLive' );
    return mod.composeVayuLokShareTitle;
  }

  it( 'includes AQI, dominant pollutant and weather when all data is present', async () => {
    const compose = await loadCompose();
    const title = compose(
      'Mumbai',
      { aqi: 142.6, word: 'Unhealthy', sev: 4 as any, dominant: 'PM2.5', pollutants: [] },
      { temp: 31, condition: 'Haze' },
    );
    expect( title ).toBe( 'Air quality in Mumbai: AQI 143 (Unhealthy), PM2.5 dominant - 31°C, Haze | VayuLok' );
    expect( title ).not.toContain( 'NaN' );
    expect( title ).not.toContain( 'undefined' );
  } );

  it( 'includes only the air clause when weather is null (air-only)', async () => {
    const compose = await loadCompose();
    const title = compose(
      'Delhi',
      { aqi: 205, word: 'Very Unhealthy', sev: 5 as any, pollutants: [] },
      null,
    );
    expect( title ).toBe( 'Air quality in Delhi: AQI 205 (Very Unhealthy) | VayuLok' );
    expect( title ).not.toContain( '°C' );
  } );

  it( 'includes only the weather clause when air is null (weather-only)', async () => {
    const compose = await loadCompose();
    const title = compose( 'Shillong', null, { temp: 18, condition: 'Light rain' } );
    expect( title ).toBe( 'Shillong: 18°C, Light rain | VayuLok' );
    expect( title ).not.toContain( 'AQI' );
  } );

  it( 'is the place name alone when air and weather are both null (place-only / keyless)', async () => {
    const compose = await loadCompose();
    const title = compose( 'Lumpyngngad', null, null );
    expect( title ).toBe( 'Lumpyngngad | VayuLok' );
    expect( title ).not.toContain( 'AQI' );
    expect( title ).not.toContain( '°C' );
    expect( title ).not.toContain( 'NaN' );
    expect( title ).not.toContain( 'undefined' );
  } );

  it( 'falls back to the neutral VayuLok title when the place name is empty', async () => {
    const compose = await loadCompose();
    expect( compose( '', null, null ) ).toBe( 'VayuLok - live air quality across India' );
    expect( compose( '   ', null, null ) ).toBe( 'VayuLok - live air quality across India' );
    expect( compose( undefined, null, null ) ).toBe( 'VayuLok - live air quality across India' );
  } );

  it( 'never emits a fabricated number: drops a non-finite AQI or temp honestly', async () => {
    const compose = await loadCompose();
    // Non-finite aqi -> no air clause; absent temp but present condition -> condition only.
    const title = compose(
      'Pune',
      { aqi: NaN, word: 'Good', sev: 1 as any, pollutants: [] },
      { condition: 'Clear' },
    );
    expect( title ).toBe( 'Pune: Clear | VayuLok' );
    expect( title ).not.toContain( 'AQI' );
    expect( title ).not.toContain( 'NaN' );
    expect( title ).not.toContain( 'undefined' );
  } );
} );
