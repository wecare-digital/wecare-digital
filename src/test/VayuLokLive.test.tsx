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

// Optional author attribution Google supplies with a Place photo. When provided, the
// stubbed search prediction resolves to a Place carrying one photo with these
// attributions, so the component's mandated-attribution rendering can be exercised.
interface PhotoAttribution { displayName?: string; uri?: string }
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
  photoAttributions?: PhotoAttribution[];
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
    photoAttributions,
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
    imageMapTypeOpts: [],
    geocodeCalls: [],
    autocompleteCalls: [],
    placeFetchFields: [],
    importedLibraries: [],
    markerOpts: [],
    fitBoundsCalls: [],
    setZoomCalls: [],
  };

  const overlayMapTypes = {
    clear: () => { rec.overlayClears += 1; },
    push: ( t: unknown ) => { rec.overlayPushes.push( t ); },
  };

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
    constructor( opts: Record<string, unknown> ) { rec.imageMapTypeOpts.push( opts ); }
  }
  class FakeAutocompleteSessionToken {}
  // When photoAttributions are supplied, the resolved Place carries one photo bearing those
  // Google-mandated author attributions (getURI returns a stable URL). Otherwise photos stay
  // empty, preserving the default stub behaviour the other suites rely on.
  const predictionPhotos = photoAttributions
    ? [ {
        getURI: ( _o: { maxWidth?: number; maxHeight?: number } ) => 'https://maps.example/photo-with-credit.jpg',
        authorAttributions: photoAttributions,
      } ]
    : [];
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
      photos: predictionPhotos,
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
  // The map search is rendered only after the Maps tilesloaded signal flips mapReady.
  // Wait for that UI boundary instead of racing it after the FakeMap constructor runs.
  const input = await screen.findByRole( 'combobox' );
  fireEvent.change( input, { target: { value: 'Mumbai' } } );
  fireEvent.mouseDown( await screen.findByRole( 'option', { name: /Mumbai/i } ) );
  await waitFor( () => {
    expect( screen.getByRole( 'button', { name: 'AQI' } ) ).not.toBeDisabled();
  } );
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
            { code: 'pm25', concentration: { value: 28, units: 'MICROGRAMS_PER_CUBIC_METER' } },
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

  it( 'loads Lumpyngngad as the default local destination while keeping the map India-scoped', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    expect( rec.mapOpts?.restriction ).toEqual( { latLngBounds: { north: 37.6, south: 6.4, west: 68.1, east: 97.4 }, strictBounds: true } );
    expect( rec.mapOpts?.center ).toEqual( { lat: 25.5586, lng: 91.8985 } );
    expect( rec.mapOpts?.zoom ).toBe( 13 );
    expect( rec.mapOpts?.zoomControl ).toBe( false );
    expect( container.querySelector( '.vl-live-map-locate' ) ).toBeNull();

    const card = await waitFor( () => {
      const el = container.querySelector( '.vl-live-place-card' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( card.textContent ).toContain( 'Lumpyngngad' );
    expect( card.textContent ).toContain( 'Shillong, Meghalaya' );
    expect( screen.queryByText( 'Search India to see live weather and air.' ) ).toBeNull();
    expect( await screen.findByRole( 'button', { name: 'AQI' } ) ).not.toBeDisabled();
    expect( await screen.findByRole( 'button', { name: 'PM2.5' } ) ).not.toBeDisabled();
    await waitFor( () => expect( fetchSpy ).toHaveBeenCalled() );
  } );

  it( 'renders the place card without internal selected-place wording and keeps the branded marker', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    const card = await waitFor( () => {
      const el = container.querySelector( '.vl-live-place-card' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( card.textContent ).toContain( 'Mumbai' );
    expect( card.textContent ).not.toContain( 'Selected place' );
    expect( container.querySelector( '.vl-live-map-locate' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-map-destbar-chevron' ) ).toBeNull();

    await waitFor( () => expect( rec.markerOpts.length ).toBeGreaterThan( 0 ) );
    const icon = rec.markerOpts[ 0 ].icon;
    expect( typeof icon ).toBe( 'string' );
    expect( decodeURIComponent( String( icon ) ) ).toContain( '#1a3a2a' );
    expect( decodeURIComponent( String( icon ) ) ).toContain( '#d1f470' );

    await waitFor( () => expect( rec.fitBoundsCalls.length ).toBeGreaterThan( 0 ) );
    expect( rec.fitBoundsCalls[ 0 ].padding ).toBe( 56 );
  } );

  it( 'renders the place photo rail with lime progress while preserving required author attribution', async () => {
    rec = installGoogleMaps( {
      photoAttributions: [ { displayName: 'Example Contributor', uri: 'https://example.com/contributor' } ],
    } );
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    const rail = await waitFor( () => {
      const el = container.querySelector( '.vl-live-photo-rail' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( rail.getAttribute( 'aria-label' ) ).toBe( 'Place photos' );
    expect( container.querySelector( '.vl-live-photo-count' ) ).toBeNull();

    const credit = container.querySelector( '.vl-live-photo-credit' );
    expect( credit?.textContent ).toContain( 'Example Contributor' );
    expect( credit?.querySelector( 'a' )?.getAttribute( 'href' ) ).toBe( 'https://example.com/contributor' );
  } );

  it( 'renders the v8 Now block, real past-now-future weather rail and Air/Weather tabs', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    // The default location can render just before the selected location clears it.
    // Assert the complete current-conditions contract in one settled render.
    await waitFor( () => {
      expect( container.querySelector( '.vl-live-now-grid' )?.textContent ).toContain( 'Satisfactory' );
      const source = container.querySelector( '.vl-live-air-source-strip' );
      expect( source?.textContent ).toContain( 'Google model' );
      expect( source?.textContent ).toContain( 'No nearby monitor reading' );
    } );

    const rail = await waitFor( () => {
      const el = container.querySelector( '.vl-live-forecast-weather' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( rail.querySelectorAll( '.vl-live-forecast-hour' ) ).toHaveLength( 5 );
    expect( rail.querySelectorAll( '.is-past' ) ).toHaveLength( 2 );
    expect( rail.querySelectorAll( '.is-now' ) ).toHaveLength( 1 );
    expect( rail.querySelectorAll( '.is-future' ) ).toHaveLength( 2 );
    expect( rail.textContent ).toContain( 'Now' );

    // Changing from the default place to Mumbai clears/reloads current conditions.
    // Wait for the post-selection detail UI rather than observing the brief stale-data frame.
    const airTab = await screen.findByRole( 'tab', { name: 'Air' } );
    const weatherTab = await screen.findByRole( 'tab', { name: 'Weather' } );
    expect( airTab ).toHaveAttribute( 'aria-selected', 'true' );
    expect( container.querySelector( '[aria-label="Air details"]' ) ).not.toBeNull();

    fireEvent.click( weatherTab );
    await waitFor( () => expect( weatherTab ).toHaveAttribute( 'aria-selected', 'true' ) );
    expect( container.querySelector( '[aria-label="Weather details"]' ) ).not.toBeNull();
  } );

  it( 'uses real 24-hour weather history and requests 96 hours of AQ forecast', async () => {
    const fetchSpy = environmentFetch();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

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

    await waitFor( () => expect( container.querySelector( '.vl-live-now-context' ) ).not.toBeNull() );
    expect( container.querySelector( '.vl-live-now-context' )?.textContent ).toMatch( /24h range/ );
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

  it( 'keeps spatial AQ dots user-triggered, deck.gl based and on the no-red v8 palette', async () => {
    const fetchSpy = airConditionsFetch( 450, 180 );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    expect( deckRec.overlaySetMapCalls ).toHaveLength( 0 );
    fireEvent.click( screen.getByRole( 'button', { name: 'AQI' } ) );

    await waitFor( () => expect( deckRec.scatterProps.length ).toBeGreaterThan( 0 ) );
    const props = deckRec.scatterProps.at( -1 )!;
    const point = Array.isArray( props.data ) ? props.data[ 0 ] : null;
    expect( point ).toBeTruthy();
    const fill = props.getFillColor( point ) as [ number, number, number, number ];
    expect( matchesVayuLokRamp( fill ) ).toBe( true );
    expect( isRedDominant( fill ) ).toBe( false );
    expect( rec.imageMapTypeOpts ).toHaveLength( 0 );
    expect( deckRec.overlaySetMapCalls.some( value => Boolean( value ) ) ).toBe( true );
  } );

  it( 'shows the approved passive bottom label and no chevron/action control', async () => {
    vi.stubGlobal( 'fetch', environmentFetch() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await selectMumbai();

    const label = await waitFor( () => {
      const el = container.querySelector( '.vl-live-selected-label' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( label.tagName ).toBe( 'DIV' );
    expect( label.textContent ).toContain( 'Mumbai' );
    expect( label.querySelector( '.vl-live-map-destbar-chevron' ) ).toBeNull();
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
  it( 'shows the keyless map without injecting Maps JS or issuing environmental calls', async () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', '' );
    const fetchSpy = vi.fn();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );

    expect( document.getElementById( 'gmaps-js' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-map-canvas' ) ).toBeNull();
    const frame = container.querySelector( '.vl-live-map-embed' ) as HTMLIFrameElement | null;
    expect( frame ).not.toBeNull();
    expect( frame?.getAttribute( 'src' ) ).toContain( 'maps.google.com/maps?q=' );
    expect( fetchSpy ).not.toHaveBeenCalled();
    expect( container.textContent ).not.toContain( 'Live air quality and weather' );
    expect( container.textContent ).not.toContain( 'Selected place' );
    expect( container.textContent ).not.toContain( 'Search India to see live weather and air.' );
  } );
} );
