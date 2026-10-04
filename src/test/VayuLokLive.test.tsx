import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SITE_ORIGIN } from '../config/share';

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

// The VayuLok NO-RED severity ramp the dots must use (good -> worst). No red at any band.
const NO_RED_FILLS: [ number, number, number, number ][] = [
  [ 26, 58, 42, 210 ],
  [ 61, 163, 90, 210 ],
  [ 209, 244, 112, 210 ],
  [ 232, 197, 71, 210 ],
  [ 201, 138, 46, 210 ],
];

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
  regularOpeningHours?: { openNow?: boolean };
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
}

function installGoogleMaps( opts: boolean | InstallOpts = true ): MapsRecorder {
  const {
    paintMap = true,
    photoAttributions,
    placeMeta,
    seedNamespaceGeocoder = true,
    geocodeStatus = 'OK',
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
  };

  const overlayMapTypes = {
    clear: () => { rec.overlayClears += 1; },
    push: ( t: unknown ) => { rec.overlayPushes.push( t ); },
  };

  class FakeMap {
    overlayMapTypes = overlayMapTypes;
    constructor( _el: HTMLElement, opts: Record<string, unknown> ) { rec.mapOpts = opts; }
    setCenter() { /* no-op */ }
    addListener( eventName: string, handler: () => void ) {
      if ( eventName === 'tilesloaded' && paintMap ) requestAnimationFrame( handler );
      return { remove() { /* no-op */ } };
    }
  }
  class FakeMarker {
    constructor( _opts: Record<string, unknown> ) { /* no-op */ }
    setPosition() { /* no-op */ }
    setTitle() { /* no-op */ }
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
          ? [ {
              formatted_address: 'Mumbai, Maharashtra, India',
              place_id: 'fake-place-id',
              geometry: { location: { lat: () => 19.076, lng: () => 72.8777 } },
            } ]
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
      displayName: 'Mumbai',
      formattedAddress: 'Mumbai, Maharashtra, India',
      location: { lat: () => 19.076, lng: () => 72.8777 },
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
function airConditionsFetch( aqi = 120, pm25 = 58 ) {
  return vi.fn( ( input: RequestInfo | URL ) => {
    const url = String( input );
    if ( url.includes( 'airquality.googleapis.com/v1/currentConditions' ) ) {
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

describe( 'VayuLokLive - honest degradation when the key is absent', () => {
  beforeEach( () => {
    // Explicitly unset so the module-scope read resolves to ''.
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', '' );
  } );

  it( 'appends no Maps script, fires zero fetches, shows no spinner/placeholder, still renders', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    // Let any effects run; with no key they must early-return before touching the DOM/network.
    await act( async () => { await Promise.resolve(); } );

    // (a) No Maps JS script was injected.
    expect( document.getElementById( 'gmaps-js' ) ).toBeNull();
    // (b) The network was never touched - this is the assertion that fails if the component ever
    // fetches unconditionally instead of behind the key guard.
    expect( fetchSpy ).not.toHaveBeenCalled();
    // (b2) deck.gl is NEVER dynamically imported / attached on the no-key path: no overlay
    // instance is constructed and nothing is attached to any map.
    expect( deckRec.overlayInstances ).toBe( 0 );
    expect( deckRec.overlaySetMapCalls ).toHaveLength( 0 );
    // (c) Degradation is SILENT: no spinner, and no live-metric element rendered with a "--"/"—"
    // placeholder standing in for a value that never arrived. The map canvas and every live figure
    // are simply absent rather than shown empty. (textContent is not scanned for "--" because the
    // styled-jsx CSS custom properties legitimately contain "--".)
    expect( container.querySelector( '[role="progressbar"]' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-map-canvas' ) ).toBeNull();
    expect( container.querySelector( '[class*="vl-live-metric"]' ) ).toBeNull();
    // No visible text node that is just a dash placeholder.
    const visibleText = Array.from( container.querySelectorAll( '.vl-live-left *' ) )
      .map( n => ( n.childNodes.length === 1 && n.firstChild?.nodeType === 3 ? n.textContent || '' : '' ) );
    expect( visibleText.some( t => t.trim() === '--' || t.trim() === '\u2014' ) ).toBe( false );
    // (d) The shell still renders - the section and its (visually hidden) heading are present.
    expect( container.querySelector( 'section.vl-live' ) ).not.toBeNull();
    expect( screen.getByText( 'Live air quality and weather' ) ).toBeInTheDocument();
  } );

  it( 'still renders the reusable Subscribe / Contribute / Share blocks with no key', async () => {
    vi.stubGlobal( 'fetch', vi.fn() );
    const VayuLokLive = await loadComponent();
    const { container } = render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );

    // The map and its search are gated on the key, but the shell content is not.
    expect( container.querySelector( '.vl-live-map-canvas' ) ).toBeNull();
    const wa = screen.getByRole( 'link', { name: 'Subscribe on WhatsApp' } );
    expect( wa.getAttribute( 'href' ) ).toBe( 'https://wa.me/message/BEA3HNW3LNM3A1' );
  } );
} );

describe( 'VayuLokLive - Maps script injection guard (key present)', () => {
  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
    // No window.google yet, so the component must inject the script itself.
    clearGoogleMaps();
  } );

  it( 'injects exactly one #gmaps-js and does not append a second on remount', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    const first = render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );

    const scripts = () => document.querySelectorAll( 'script#gmaps-js' );
    expect( scripts() ).toHaveLength( 1 );

    const script = document.getElementById( 'gmaps-js' ) as HTMLScriptElement;
    // The host and the async loader flag are asserted; the KEY VALUE is deliberately NOT asserted.
    expect( script.src ).toContain( 'maps.googleapis.com/maps/api/js' );
    expect( script.src ).toContain( 'loading=async' );

    // Unmount and mount a second instance: the one-script-tag guard must reuse the existing tag.
    first.unmount();
    render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );
    expect( scripts() ).toHaveLength( 1 );
  } );

  it( 'initialises when google.maps appears asynchronously without a script load event', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );

    // Reproduce the real loading=async path: the script exists first, then the
    // Maps namespace appears later. Deliberately DO NOT dispatch a DOM load event.
    const rec = installGoogleMaps();

    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
  } );
} );

describe( 'VayuLokLive - map wiring, heatmap on user action, India scoping (key + google stub)', () => {
  let rec: MapsRecorder;

  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
    // Pre-install the Maps stub so the init runs synchronously (no script load needed) and the
    // map/overlay effects can be exercised.
    rec = installGoogleMaps();
  } );

  it( 'uses NO raster heatmap path at all - the deck.gl overlay attaches on layer click and the air grid fetches only then', async () => {
    const fetchSpy = airConditionsFetch( 120, 58 );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    // RASTER PATH IS GONE. No ImageMapType is ever constructed and no overlayMapType is ever
    // pushed - at any point, on load or after a layer click.
    expect( rec.imageMapTypeOpts ).toHaveLength( 0 );
    expect( rec.overlayPushes ).toHaveLength( 0 );

    // On load (no layer active): NO air fetch, and the deck.gl overlay is NOT attached.
    const airFetches = () => fetchSpy.mock.calls.filter(
      c => String( c[ 0 ] ).includes( 'airquality.googleapis.com/v1/currentConditions' ),
    );
    const heatmapTilesHit = () => fetchSpy.mock.calls.some( c => String( c[ 0 ] ).includes( 'heatmapTiles' ) );
    expect( airFetches() ).toHaveLength( 0 );
    expect( heatmapTilesHit() ).toBe( false );
    expect( deckRec.overlaySetMapCalls ).toHaveLength( 0 );

    await waitFor( () => expect( screen.getByRole( 'button', { name: 'AQI' } ) ).toBeInTheDocument() );

    // Activate the AQI layer.
    fireEvent.click( screen.getByRole( 'button', { name: 'AQI' } ) );

    // NOW the grid air fetch fires (currentConditions:lookup, one per grid cell) AND the
    // deck.gl overlay is attached to the Google map (setMap called with the FakeMap).
    await waitFor( () => expect( airFetches().length ).toBeGreaterThan( 0 ) );
    await waitFor( () => expect( deckRec.overlaySetMapCalls.length ).toBeGreaterThan( 0 ) );
    const map = deckRec.overlaySetMapCalls.at( -1 );
    expect( map ).not.toBeNull();
    // The overlay was attached to the SAME object the component constructed as the map
    // (FakeMap carries the India restriction options the component passed).
    expect( ( map as { overlayMapTypes?: unknown } ).overlayMapTypes ).toBeDefined();

    // Still no raster heatmap tiles were ever requested.
    expect( heatmapTilesHit() ).toBe( false );
    expect( rec.imageMapTypeOpts ).toHaveLength( 0 );

    // The overlay received at least one ScatterplotLayer carrying REAL point data.
    await waitFor( () => expect( deckRec.scatterProps.length ).toBeGreaterThan( 0 ) );
    const scatter = deckRec.scatterProps.at( -1 )!;
    expect( Array.isArray( scatter.data ) ).toBe( true );
    expect( scatter.data.length ).toBeGreaterThan( 0 );
    expect( scatter.pickable ).toBe( false );
    // Each dot's position is [lng, lat].
    const samplePos = scatter.getPosition( scatter.data[ 0 ] );
    expect( Array.isArray( samplePos ) ).toBe( true );
    expect( samplePos ).toHaveLength( 2 );

    // DOT FILL COLOURS ARE NO-RED. getFillColor for every real dot resolves to a colour in
    // the VayuLok no-red ramp, and never a red-dominant RGBA like [255,0,0].
    for ( const d of scatter.data ) {
      const fill = scatter.getFillColor( d ) as [ number, number, number, number ];
      const isNoRed = NO_RED_FILLS.some( ramp => ramp[ 0 ] === fill[ 0 ] && ramp[ 1 ] === fill[ 1 ] && ramp[ 2 ] === fill[ 2 ] );
      expect( isNoRed ).toBe( true );
      // Hard guard: never a red-dominant fill (R high while G and B low).
      expect( fill[ 0 ] > 200 && fill[ 1 ] < 80 && fill[ 2 ] < 80 ).toBe( false );
    }

    // Deactivating the layer (second click -> layer null) CLEARS the overlay: it is detached
    // from the map (setMap(null)) and/or given an empty layers array.
    fireEvent.click( screen.getByRole( 'button', { name: 'AQI' } ) );
    await waitFor( () => {
      const detached = deckRec.overlaySetMapCalls.at( -1 ) === null;
      const emptied = deckRec.overlaySetPropsCalls.at( -1 )?.layers.length === 0;
      expect( detached || emptied ).toBe( true );
    } );
  } );

  it( 'switching AQI -> PM2.5 keeps using the deck.gl overlay (never a raster ImageMapType)', async () => {
    const fetchSpy = airConditionsFetch( 120, 58 );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await waitFor( () => expect( screen.getByRole( 'button', { name: 'AQI' } ) ).toBeInTheDocument() );

    fireEvent.click( screen.getByRole( 'button', { name: 'AQI' } ) );
    await waitFor( () => expect( deckRec.scatterProps.length ).toBeGreaterThan( 0 ) );
    const aqiLayers = deckRec.scatterProps.length;

    fireEvent.click( screen.getByRole( 'button', { name: 'PM2.5' } ) );
    await waitFor( () => expect( deckRec.scatterProps.length ).toBeGreaterThan( aqiLayers ) );

    // No raster path was taken for either layer.
    expect( rec.imageMapTypeOpts ).toHaveLength( 0 );
    expect( fetchSpy.mock.calls.some( c => String( c[ 0 ] ).includes( 'heatmapTiles' ) ) ).toBe( false );

    // The PM2.5 scatter layer still paints no-red fills.
    const pm25Scatter = deckRec.scatterProps.at( -1 )!;
    for ( const d of pm25Scatter.data ) {
      const fill = pm25Scatter.getFillColor( d ) as [ number, number, number, number ];
      expect( fill[ 0 ] > 200 && fill[ 1 ] < 80 && fill[ 2 ] < 80 ).toBe( false );
    }
  } );

  it( 'typing or selecting a place fires ZERO air/weather/pollen fetches (only a layer click does)', async () => {
    const fetchSpy = airConditionsFetch( 120, 58 );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    const envFetches = () => fetchSpy.mock.calls.filter( c => {
      const u = String( c[ 0 ] );
      return u.includes( 'airquality.googleapis.com' )
        || u.includes( 'weather.googleapis.com' )
        || u.includes( 'pollen.googleapis.com' );
    } );

    // Type a query and select the resolved place.
    fireEvent.change( screen.getByRole( 'combobox' ), { target: { value: 'Mumbai' } } );
    fireEvent.mouseDown( await screen.findByRole( 'option', { name: /Mumbai/i } ) );
    await waitFor( () => expect(
      ( screen.getByText( /Mumbai/i ) ),
    ).toBeTruthy() );

    // Let any stray effects settle: still ZERO air/weather/pollen network calls, because
    // selecting a place no longer triggers environmental fetches.
    await act( async () => { await Promise.resolve(); await Promise.resolve(); } );
    expect( envFetches() ).toHaveLength( 0 );
    // And the deck.gl overlay has not been attached (no layer active).
    expect( deckRec.overlaySetMapCalls ).toHaveLength( 0 );

    // Only after a layer click do air fetches begin.
    await waitFor( () => expect( screen.getByRole( 'button', { name: 'AQI' } ) ).toBeInTheDocument() );
    fireEvent.click( screen.getByRole( 'button', { name: 'AQI' } ) );
    await waitFor( () => expect( envFetches().length ).toBeGreaterThan( 0 ) );
    // Everything fetched is the Air Quality currentConditions grid - no weather/pollen.
    expect( envFetches().every( c => String( c[ 0 ] ).includes( 'airquality.googleapis.com/v1/currentConditions' ) ) ).toBe( true );
  } );

  it( 'shows the heatmap legend only while a layer is active, with both ends labelled in words', async () => {
    // The legend now lives inside the left card's environmental RESULT block, which renders
    // once a layer is active AND the air reading has arrived. Supply a minimal AQI response.
    vi.stubGlobal( 'fetch', vi.fn( ( input: RequestInfo | URL ) => {
      const url = String( input );
      if ( url.includes( 'airquality.googleapis.com/v1/currentConditions' ) ) {
        return Promise.resolve( {
          ok: true,
          json: async () => ( {
            dateTime: new Date().toISOString(),
            indexes: [ { code: 'ind_cpcb', aqi: 120, category: 'Moderate', dominantPollutant: 'pm25' } ],
            pollutants: [ { code: 'pm25', concentration: { value: 58, units: 'MICROGRAMS_PER_CUBIC_METER' } } ],
          } ),
        } as Response );
      }
      return Promise.resolve( { ok: false, json: async () => ( {} ) } as Response );
    } ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await waitFor( () => expect( screen.getByRole( 'button', { name: 'AQI' } ) ).toBeInTheDocument() );

    // No layer selected on load -> no legend in the DOM.
    expect( container.querySelector( '.vl-live-scale-legend' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-scale' ) ).toBeNull();

    // Activating a layer reveals the legend, which reuses the no-red --aqi-* ramp and
    // labels both ends in WORDS so colour is never the sole carrier of meaning.
    fireEvent.click( screen.getByRole( 'button', { name: 'AQI' } ) );
    await waitFor( () => expect( container.querySelector( '.vl-live-scale-legend' ) ).not.toBeNull() );
    expect( container.querySelector( '.vl-live-scale-legend .vl-live-scale' ) ).not.toBeNull();
    const ends = Array.from( container.querySelectorAll( '.vl-live-scale-ends span' ) ).map( n => n.textContent );
    expect( ends ).toEqual( [ 'Good', 'Hazardous' ] );
  } );

  it( 'renders the selected place name + address in the left card and swaps the result block per layer', async () => {
    const fetchSpy = vi.fn( ( input: RequestInfo | URL ) => {
      const url = String( input );
      if ( url.includes( 'airquality.googleapis.com/v1/currentConditions' ) ) {
        return Promise.resolve( {
          ok: true,
          json: async () => ( {
            dateTime: new Date().toISOString(),
            indexes: [ { code: 'ind_cpcb', aqi: 168, category: 'Moderate', dominantPollutant: 'pm25' } ],
            pollutants: [ { code: 'pm25', concentration: { value: 82, units: 'MICROGRAMS_PER_CUBIC_METER' } } ],
            healthRecommendations: { generalPopulation: 'Limit prolonged outdoor exertion.' },
          } ),
        } as Response );
      }
      return Promise.resolve( { ok: false, json: async () => ( {} ) } as Response );
    } );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    // The left card always leads with the selected place's name + full address.
    const leftCard = container.querySelector( '.vl-live-left .vl-live-place-card' );
    expect( leftCard ).not.toBeNull();
    expect( leftCard!.querySelector( '.vl-live-place' )?.textContent ).toBeTruthy();
    expect( leftCard!.querySelector( '.vl-live-place-addr' )?.textContent ).toBeTruthy();

    // No layer selected -> no environmental result block in the card yet.
    expect( container.querySelector( '.vl-live-layer-result' ) ).toBeNull();

    // Wait for the AQI figure to arrive from the stubbed air endpoint.
    await waitFor( () => expect( screen.getByRole( 'button', { name: 'AQI' } ) ).toBeInTheDocument() );
    fireEvent.click( screen.getByRole( 'button', { name: 'AQI' } ) );

    // Selecting AQI renders the existing VayuLok AQI result INSIDE the left card: the AQI
    // value, its category word, and the health guidance all appear in the left column.
    await waitFor( () => expect( container.querySelector( '.vl-live-left .vl-live-layer-result' ) ).not.toBeNull() );
    const aqiResult = container.querySelector( '.vl-live-left .vl-live-layer-result' ) as HTMLElement;
    expect( aqiResult.textContent ).toContain( '168' );
    expect( aqiResult.textContent ).toContain( 'Moderate' );
    expect( aqiResult.textContent ).toContain( 'Air quality now' );

    // Switching to PM2.5 swaps the left-card result to the PM2.5-focused block, which
    // carries the explicit "Current status" label + a status word derived from the SAME
    // severity band (168 -> Moderate -> "Elevated"), per the FINAL TARGET PM2.5 mockup.
    fireEvent.click( screen.getByRole( 'button', { name: 'PM2.5' } ) );
    await waitFor( () => {
      const pm25Result = container.querySelector( '.vl-live-left .vl-live-layer-result' ) as HTMLElement;
      expect( pm25Result.textContent ).toContain( 'PM2.5 heatmap result' );
      expect( pm25Result.textContent ).toContain( '82' );
      expect( pm25Result.textContent ).toContain( 'Current status' );
      expect( pm25Result.querySelector( '.vl-live-status-word' )?.textContent ).toBe( 'Elevated' );
    } );
  } );

  it( 'builds the map restricted to India and searches India-scoped (not duplicated literals)', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    // The real options the component passed to google.maps.Map: an India latLngBounds restriction.
    const restriction = rec.mapOpts!.restriction as { latLngBounds: { north: number; south: number; east: number; west: number } };
    const b = restriction.latLngBounds;
    // India's extent: north of the equator, east of the prime meridian, spanning roughly 6-38N /
    // 68-98E. Asserted as a plausibility envelope, not a copy of the literal, so the test tracks the
    // component's constant without re-stating it.
    expect( b.south ).toBeGreaterThan( 0 );
    expect( b.south ).toBeLessThan( b.north );
    expect( b.west ).toBeGreaterThan( 60 );
    expect( b.west ).toBeLessThan( b.east );
    expect( b.north ).toBeLessThan( 40 );
    expect( b.east ).toBeLessThan( 100 );
    expect( restriction ).toMatchObject( { strictBounds: true } );
    expect( rec.mapOpts!.disableDefaultUI ).toBe( true );
    expect( rec.mapOpts!.fullscreenControl ).toBe( false );
    expect( rec.mapOpts!.mapTypeControl ).toBe( false );
    expect( rec.mapOpts!.streetViewControl ).toBe( false );
    expect( rec.mapOpts!.keyboardShortcuts ).toBe( false );

    // The default centre sits inside the restriction bounds (so the map opens on India).
    const centre = rec.mapOpts!.center as { lat: number; lng: number };
    expect( centre.lat ).toBeGreaterThan( b.south );
    expect( centre.lat ).toBeLessThan( b.north );
    expect( centre.lng ).toBeGreaterThan( b.west );
    expect( centre.lng ).toBeLessThan( b.east );

    // Search is India-scoped and uses the modern Autocomplete Data API with a
    // session token, not legacy Text Search on each keystroke.
    const input = screen.getByRole( 'combobox' );
    fireEvent.change( input, { target: { value: 'Mumbai' } } );
    await waitFor( () => expect( rec.autocompleteCalls.length ).toBeGreaterThan( 0 ) );
    expect( rec.autocompleteCalls[ 0 ].region ).toBe( 'in' );
    expect( rec.autocompleteCalls[ 0 ].includedRegionCodes ).toEqual( [ 'in' ] );
    expect( rec.autocompleteCalls[ 0 ].sessionToken ).toBeTruthy();
    const loc = rec.autocompleteCalls[ 0 ].locationRestriction as { north: number; south: number };
    expect( loc.south ).toBeGreaterThan( 0 );
    expect( loc.north ).toBeLessThan( 40 );

    // Resolving the prediction requests only the fields VayuLok needs.
    await waitFor( () => expect( screen.getByRole( 'option', { name: /Mumbai/i } ) ).toBeInTheDocument() );
    fireEvent.mouseDown( screen.getByRole( 'option', { name: /Mumbai/i } ) );
    await waitFor( () => expect( rec.placeFetchFields.length ).toBeGreaterThan( 0 ) );
    expect( rec.placeFetchFields[ 0 ] ).toEqual( expect.arrayContaining( [ 'displayName', 'formattedAddress', 'location', 'photos' ] ) );
  } );

  it( 'no longer renders the on-map Expand/Collapse control, and keeps greedy drag-pan', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    // Wait for the ready-only controls so the right-map chrome has rendered.
    await waitFor( () => expect( screen.getByRole( 'button', { name: 'AQI' } ) ).toBeInTheDocument() );

    // FINAL TARGET: the Expand map / Collapse map control is REMOVED from the map. No
    // button carries either accessible name, and the expand-only CSS hook is gone.
    expect( screen.queryByRole( 'button', { name: 'Expand map' } ) ).toBeNull();
    expect( screen.queryByRole( 'button', { name: 'Collapse map' } ) ).toBeNull();
    expect( container.querySelector( '.vl-live-map-expand' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-map-stage.is-expanded' ) ).toBeNull();

    // Basic usable map pan is kept via gestureHandling:'greedy'; keyboardShortcuts stays
    // false so Google's built-in arrow-pan never fights the India strictBounds restriction.
    expect( rec.mapOpts!.gestureHandling ).toBe( 'greedy' );
    expect( rec.mapOpts!.keyboardShortcuts ).toBe( false );
  } );

  it( 'does not float a photo gallery overlay on the map (photo + pill live in the left card)', async () => {
    const rec2 = installGoogleMaps( {
      photoAttributions: [ { displayName: 'Jane Contributor', uri: 'https://maps.google.com/maps/contrib/123' } ],
    } );
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec2.mapOpts ).not.toBeNull() );

    // Drive search -> select so photos resolve into previewPlace.photos.
    const input = screen.getByRole( 'combobox' );
    fireEvent.change( input, { target: { value: 'Mumbai' } } );
    const option = await screen.findByRole( 'option', { name: /Mumbai/i } );
    fireEvent.mouseDown( option );

    // The number pill renders (number-only), and it lives INSIDE the left column, not in
    // a floating on-map overlay. The removed overlay container is gone from the DOM.
    const pill = await waitFor( () => {
      const el = container.querySelector( '.vl-live-photo-count' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( container.querySelector( '.vl-live-map-photos' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-left .vl-live-photo-count' ) ).not.toBeNull();
    expect( container.querySelector( '.vl-live-right .vl-live-photo-count' ) ).toBeNull();

    // The pill is number-only: its visible text is a bare integer, never '{n} photos'.
    const visible = ( pill.textContent || '' ).trim();
    expect( visible ).toMatch( /^\d+$/ );
    expect( visible ).not.toMatch( /photo/i );
  } );

  it( 'surfaces real Place metadata/attributes/description in the left card ONLY when Google returned it', async () => {
    const rec2 = installGoogleMaps( {
      placeMeta: {
        primaryTypeDisplayName: 'Historical landmark',
        types: [ 'tourist_attraction', 'point_of_interest' ],
        rating: 4.6,
        userRatingCount: 1234,
        websiteURI: 'https://example.gov.in/monument',
        regularOpeningHours: { openNow: true },
        editorialSummary: 'A heritage monument popular with visitors.',
      },
    } );
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec2.mapOpts ).not.toBeNull() );

    // Before a selection the default place carries no Google metadata, so none of the
    // metadata-fact/attribute/description lines render (honest conditional, no placeholder).
    expect( container.querySelector( '.vl-live-place-facts' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-place-attrs' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-place-desc' ) ).toBeNull();

    // Drive search -> select so the Place metadata resolves into the left card.
    fireEvent.change( screen.getByRole( 'combobox' ), { target: { value: 'Mumbai' } } );
    fireEvent.mouseDown( await screen.findByRole( 'option', { name: /Mumbai/i } ) );

    const meta = await waitFor( () => {
      const el = container.querySelector( '.vl-live-left .vl-live-place-meta' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );

    // The extra metadata fields were actually requested on the keyed select path.
    expect( rec2.placeFetchFields[ 0 ] ).toEqual(
      expect.arrayContaining( [ 'types', 'rating', 'userRatingCount', 'websiteURI', 'regularOpeningHours', 'editorialSummary' ] ),
    );

    // Real metadata facts render (category + rating with review count).
    expect( meta.textContent ).toContain( 'Historical Landmark' );
    expect( meta.textContent ).toContain( '4.6' );
    expect( meta.textContent ).toContain( '1,234' );

    // The attribute checklist reflects honest flags (open now, website) and the
    // human-readable secondary types - never an invented attribute.
    const attrs = Array.from( meta.querySelectorAll( '.vl-live-place-attrs li' ) ).map( n => n.textContent?.trim() );
    expect( attrs ).toContain( 'Open now' );
    expect( attrs ).toContain( 'Official website listed' );
    expect( attrs.some( a => /Tourist Attraction/i.test( a || '' ) ) ).toBe( true );

    // The editorial summary becomes the useful place description.
    expect( meta.querySelector( '.vl-live-place-desc' )?.textContent ).toContain( 'heritage monument' );
  } );

  it( 'renders NO metadata/attribute/description lines when Google returns none (honest degradation of the card body)', async () => {
    // Default stub resolves a Place with name/address/location only (no metadata).
    const rec2 = installGoogleMaps();
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec2.mapOpts ).not.toBeNull() );

    fireEvent.change( screen.getByRole( 'combobox' ), { target: { value: 'Mumbai' } } );
    fireEvent.mouseDown( await screen.findByRole( 'option', { name: /Mumbai/i } ) );

    // The place name updates, confirming the selection resolved...
    await waitFor( () => expect(
      container.querySelector( '.vl-live-left .vl-live-place' )?.textContent,
    ).toContain( 'Mumbai' ) );

    // ...but with no metadata returned, the metadata facts/attribute/description blocks do
    // not render (the supporting-info coordinate line may still appear, which is honest).
    expect( container.querySelector( '.vl-live-place-facts' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-place-attrs' ) ).toBeNull();
    expect( container.querySelector( '.vl-live-place-desc' ) ).toBeNull();
  } );
} );

describe( 'VayuLokLive - FINAL AGREED DESIGN pill + focus-ring restyle (FEAT-003)', () => {
  let rec: MapsRecorder;
  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
    rec = installGoogleMaps();
  } );

  // The component ships its CSS through styled-jsx, which injects <style> tags. Collapse
  // every rendered <style> block into one normalised string so we can assert on the ACTUAL
  // declarations the AQI/PM2.5 pills and the search field receive, without pinning exact
  // whitespace or source line numbers.
  const collectCss = () => Array.from( document.querySelectorAll( 'style' ) )
    .map( s => s.textContent || '' )
    .join( '\n' )
    .replace( /\s+/g, ' ' );

  it( 'the inactive AQI/PM2.5 pills drop the frosted white fill + backdrop blur and the active pill gets a translucent lime fill', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    const aqi = await screen.findByRole( 'button', { name: 'AQI' } );
    const pm25 = screen.getByRole( 'button', { name: 'PM2.5' } );

    // BEHAVIOUR: both pills start un-pressed (inactive) and the pill is the styled hook.
    expect( aqi.className ).toContain( 'vl-live-layer' );
    expect( aqi.getAttribute( 'aria-pressed' ) ).toBe( 'false' );
    expect( pm25.getAttribute( 'aria-pressed' ) ).toBe( 'false' );

    const css = collectCss();
    // The resting .vl-live-layer rule exists but no longer carries the old frosted look:
    // no rgba(255,255,255,.58) fill and no backdrop blur anywhere in the pill chrome.
    const restingRule = css.match( /\.vl-live-layer\{[^}]*\}/ )?.[ 0 ] ?? '';
    expect( restingRule ).not.toBe( '' );
    expect( restingRule ).toContain( 'background:transparent' );
    expect( restingRule ).not.toContain( 'rgba(255,255,255,.58)' );
    expect( restingRule ).not.toMatch( /backdrop-filter/ );
    // Dark-green outline + text at rest (colour never carried by a frosted fill).
    expect( restingRule ).toContain( '#1a3a2a' );

    // The ACTIVE (aria-pressed=true) rule carries a translucent lime fill (#d1f470-based)
    // with dark-green text/border - NOT the fully-opaque var(--lime).
    const activeRule = css.match( /\.vl-live-layer\[aria-pressed="true"\]\{[^}]*\}/ )?.[ 0 ] ?? '';
    expect( activeRule ).not.toBe( '' );
    expect( activeRule ).toMatch( /rgba\(209,\s?244,\s?112,/ );
    expect( activeRule ).toContain( 'color:#1a3a2a' );
    expect( activeRule ).toContain( 'border-color:#1a3a2a' );

    // BEHAVIOUR: clicking AQI flips its aria-pressed to true (so the active rule applies),
    // while PM2.5 stays inactive - the restyle is driven by this honest state toggle.
    fireEvent.click( aqi );
    await waitFor( () => expect( aqi.getAttribute( 'aria-pressed' ) ).toBe( 'true' ) );
    expect( pm25.getAttribute( 'aria-pressed' ) ).toBe( 'false' );
  } );

  it( 'the search field focus ring is dark-green (not translucent lime) with a single outer border', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    const css = collectCss();
    const focusRule = css.match( /\.vl-live-search-field:focus-within\{[^}]*\}/ )?.[ 0 ] ?? '';
    expect( focusRule ).not.toBe( '' );
    // The ring is dark-green, never the old translucent-lime outline.
    expect( focusRule ).toContain( 'outline:3px solid #1a3a2a' );
    expect( focusRule ).not.toContain( 'rgba(209,244,112,.78)' );

    // The field still owns a single outer dark-green border with a white (non-frosted-reliant) bg.
    const fieldRule = css.match( /\.vl-live-search-field\{[^}]*\}/ )?.[ 0 ] ?? '';
    expect( fieldRule ).toContain( 'border:2px solid #1a3a2a' );
  } );

  it( 'the photo count pill uses the exact WECARE lime (#d1f470 via --lime) and no stray #f5fde0 lime surface', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    const css = collectCss();
    const pillRule = css.match( /\.vl-live-photo-count\{[^}]*\}/ )?.[ 0 ] ?? '';
    expect( pillRule ).not.toBe( '' );
    // The pill lime is the exact token (--lime === #d1f470); it must not fall back to the
    // pale #f5fde0 map tint.
    expect( pillRule ).toContain( 'background:var(--lime)' );
    expect( pillRule ).not.toContain( '#f5fde0' );
  } );
} );

describe( 'VayuLokLive - selecting a place no longer auto-fetches weather/pollen/forecast (FEAT-002)', () => {
  let rec: MapsRecorder;
  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
    rec = installGoogleMaps();
  } );

  it( 'fires NO weather/pollen/forecast/history/solar fetch on load OR on place select', async () => {
    const fetchSpy = airConditionsFetch( 120, 58 );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    const touched = ( host: string ) => fetchSpy.mock.calls.some( c => String( c[ 0 ] ).includes( host ) );

    // On load: none of the environmental SKUs were touched.
    expect( touched( 'weather.googleapis.com' ) ).toBe( false );
    expect( touched( 'pollen.googleapis.com' ) ).toBe( false );
    expect( touched( 'solar.googleapis.com' ) ).toBe( false );
    expect( touched( 'airquality.googleapis.com/v1/forecast' ) ).toBe( false );
    expect( touched( 'airquality.googleapis.com/v1/history' ) ).toBe( false );
    expect( touched( 'airquality.googleapis.com/v1/currentConditions' ) ).toBe( false );

    // Select a place.
    fireEvent.change( screen.getByRole( 'combobox' ), { target: { value: 'Mumbai' } } );
    fireEvent.mouseDown( await screen.findByRole( 'option', { name: /Mumbai/i } ) );
    await act( async () => { await Promise.resolve(); await Promise.resolve(); } );

    // Still none - selecting a place is not a trigger for ANY environmental fetch.
    expect( touched( 'weather.googleapis.com' ) ).toBe( false );
    expect( touched( 'pollen.googleapis.com' ) ).toBe( false );
    expect( touched( 'solar.googleapis.com' ) ).toBe( false );
    expect( touched( 'airquality.googleapis.com/v1/forecast' ) ).toBe( false );
    expect( touched( 'airquality.googleapis.com/v1/history' ) ).toBe( false );
    expect( touched( 'airquality.googleapis.com/v1/currentConditions' ) ).toBe( false );
  } );

  it( 'does NOT render the retired forecast/weather sections (they are no longer fetched)', async () => {
    const fetchSpy = airConditionsFetch( 120, 58 );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    // The former auto-populated sections never appear, because their data is never fetched.
    expect( screen.queryByRole( 'heading', { name: 'Next 24 hours' } ) ).toBeNull();
    expect( screen.queryByText( '10-day outlook' ) ).toBeNull();
    expect( screen.queryByText( 'Past 24 hours' ) ).toBeNull();
    expect( screen.queryByRole( 'heading', { name: 'Air intelligence' } ) ).toBeNull();
    expect( screen.queryByText( 'Best outside' ) ).toBeNull();
  } );

  it( 'the ONLY air fetch after a layer click is the currentConditions grid - no weather/pollen', async () => {
    const fetchSpy = airConditionsFetch( 120, 58 );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );
    await waitFor( () => expect( screen.getByRole( 'button', { name: 'AQI' } ) ).toBeInTheDocument() );

    fireEvent.click( screen.getByRole( 'button', { name: 'AQI' } ) );
    await waitFor( () => expect(
      fetchSpy.mock.calls.some( c => String( c[ 0 ] ).includes( 'airquality.googleapis.com/v1/currentConditions' ) ),
    ).toBe( true ) );

    // Everything fetched is the grid; weather/pollen/forecast/history/solar stay untouched.
    for ( const call of fetchSpy.mock.calls ) {
      const u = String( call[ 0 ] );
      if ( u.includes( 'googleapis.com' ) ) {
        expect( u ).toContain( 'airquality.googleapis.com/v1/currentConditions' );
      }
    }
  } );
} );

describe( 'VayuLokLive - failure and cost controls', () => {
  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
  } );

  it( 'shows unavailable + retry when map tiles never paint', async () => {
    vi.useFakeTimers();
    const rec = installGoogleMaps( false );
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );

    await act( async () => { await Promise.resolve(); await Promise.resolve(); } );
    expect( rec.mapOpts ).not.toBeNull();

    await act( async () => { await vi.advanceTimersByTimeAsync( 12_100 ); } );
    expect( screen.getByText( 'Map temporarily unavailable.' ) ).toBeInTheDocument();
    expect( screen.getByRole( 'button', { name: 'Retry map' } ) ).toBeInTheDocument();
  } );

  it( 'does not call Solar until the visitor asks for rooftop potential', async () => {
    installGoogleMaps();
    const fetchSpy = vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );

    await waitFor( () => expect( screen.getByRole( 'button', { name: 'View solar potential' } ) ).toBeInTheDocument() );
    expect( fetchSpy.mock.calls.some( call => String( call[ 0 ] ).includes( 'solar.googleapis.com' ) ) ).toBe( false );

    fireEvent.click( screen.getByRole( 'button', { name: 'View solar potential' } ) );
    await waitFor( () => expect(
      fetchSpy.mock.calls.some( call => String( call[ 0 ] ).includes( 'solar.googleapis.com' ) )
    ).toBe( true ) );
  } );
} );

describe( 'VayuLokLive - reuse and the exact Subscribe URL (key present)', () => {
  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
    installGoogleMaps();
  } );

  it( 'renders the exact wa.me subscribe anchor and the Contribute + Share blocks', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );

    // SUBSCRIBE: the exact URL from the user instruction, opening in a new tab, with noopener.
    const wa = screen.getByRole( 'link', { name: 'Subscribe on WhatsApp' } );
    expect( wa.getAttribute( 'href' ) ).toBe( 'https://wa.me/message/BEA3HNW3LNM3A1' );
    expect( wa.getAttribute( 'target' ) ).toBe( '_blank' );
    expect( wa.getAttribute( 'rel' ) ).toContain( 'noopener' );

    // CONTRIBUTE: BlogContribution renders its "Contribute" heading and submit button.
    expect( screen.getByRole( 'heading', { name: 'Contribute' } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'button', { name: 'Contribute' } ) ).toBeInTheDocument();

    // SHARE: ShareLinks renders the canonical /vayulok/ WhatsApp share control. Its accessible
    // name ('Share this page on WhatsApp') is distinct from the Subscribe anchor above.
    const share = screen.getByRole( 'link', { name: 'Share this page on WhatsApp' } );
    expect( share.getAttribute( 'href' ) ).toContain( encodeURIComponent( `${SITE_ORIGIN}/vayulok/` ) );
    expect( container.querySelector( '.share-row' ) ).not.toBeNull();
  } );

  it( 'no longer renders the removed map place card (name/metrics/insight/view-details overlay)', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await act( async () => { await Promise.resolve(); } );

    // Requirement 02: the absolutely-positioned place card is gone from the DOM entirely.
    expect( container.querySelector( '.vl-live-map-preview' ) ).toBeNull();
    // Its CTA (and the former 'Jump to details' label) must not be present anywhere.
    expect( screen.queryByRole( 'button', { name: /View details|Jump to details/i } ) ).toBeNull();
    // The old '{n} photos' pill label text is gone - the pill is now number-only.
    expect( screen.queryByText( /\bphotos\b/i ) ).toBeNull();
  } );
} );

describe( 'VayuLokLive - geocoding library is imported and the geocoding search fallback works', () => {
  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
  } );

  // The defect: the component imported maps/marker/places but took Geocoder from the raw
  // namespace and never imported the 'geocoding' library. Under loading=async the raw
  // namespace Geocoder is undefined until importLibrary('geocoding') runs. This test
  // reproduces the real loader by NOT seeding google.maps.Geocoder, then proves the
  // component still obtains a Geocoder - which can only happen if it imports 'geocoding'.
  it( 'imports the "geocoding" library on map init even when google.maps.Geocoder is NOT pre-seeded', async () => {
    const rec = installGoogleMaps( { seedNamespaceGeocoder: false } );
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    // Hard proof there is no raw-namespace Geocoder masking the import.
    expect( ( window as unknown as { google?: { maps?: { Geocoder?: unknown } } } ).google?.maps?.Geocoder )
      .toBeUndefined();
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    // 'geocoding' is among the dynamically imported libraries, alongside the map library.
    await waitFor( () => expect( rec.importedLibraries ).toContain( 'geocoding' ) );
    expect( rec.importedLibraries ).toContain( 'maps' );
  } );

  // The autocomplete->geocoding FALLBACK: when the modern Autocomplete Data API is absent,
  // the search must still resolve via a Geocoder obtained through importLibrary('geocoding')
  // (NOT a pre-seeded namespace), proving the fallback no longer depends on legacy.Geocoder.
  it( 'resolves a search via the imported Geocoder when AutocompleteSuggestion is unavailable', async () => {
    const rec = installGoogleMaps( { seedNamespaceGeocoder: false } );
    // Remove the modern Autocomplete Data API so runSearch takes the geocoding fallback.
    delete ( ( window as unknown as { google: { maps: { places: Record<string, unknown> } } } )
      .google.maps.places ).AutocompleteSuggestion;
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    const input = screen.getByRole( 'combobox' );
    fireEvent.change( input, { target: { value: 'Mumbai' } } );

    // The fallback actually calls Geocoder.geocode with the India address restriction, and
    // the imported Geocoder (not a namespace one) returns a result the user can pick.
    await waitFor( () => expect( rec.geocodeCalls.length ).toBeGreaterThan( 0 ) );
    const addressCall = rec.geocodeCalls.find( c => typeof c.address === 'string' );
    expect( addressCall ).toBeTruthy();
    expect( ( addressCall!.componentRestrictions as { country?: string } ).country ).toBe( 'in' );
    expect( rec.importedLibraries ).toContain( 'geocoding' );
    await waitFor( () => expect( screen.getByRole( 'option', { name: /Mumbai/i } ) ).toBeInTheDocument() );
  } );

  // Error surfacing: a REQUEST_DENIED geocode status must raise the existing 'unavailable'
  // search status (amber retry affordance), not be silently swallowed.
  it( 'surfaces a REQUEST_DENIED geocode status as the "unavailable" search status with a retry', async () => {
    const rec = installGoogleMaps( { seedNamespaceGeocoder: false, geocodeStatus: 'REQUEST_DENIED' } );
    delete ( ( window as unknown as { google: { maps: { places: Record<string, unknown> } } } )
      .google.maps.places ).AutocompleteSuggestion;
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    const input = screen.getByRole( 'combobox' );
    fireEvent.change( input, { target: { value: 'Mumbai' } } );

    await waitFor( () => expect( rec.geocodeCalls.length ).toBeGreaterThan( 0 ) );
    // The failure is user-visible via the existing error status + Retry button, not swallowed.
    const status = await waitFor( () => {
      const el = container.querySelector( '.vl-live-search-status.vl-live-search-status-error' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    expect( status.querySelector( 'button' )?.textContent ).toMatch( /Retry/i );
  } );
} );

describe( 'VayuLokLive - mandated Google Place Photo attribution is preserved (req 06)', () => {
  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
  } );

  // Req 06 is bounded: the Place Photo AUTHOR attribution is mandatory under Google's Places
  // API / Maps Platform ToS and MUST stay visible and legible. This test guards against a
  // future accidental removal: a chosen place whose photo carries authorAttributions MUST
  // render the .vl-live-photo-credit <figcaption> and a link out to the contributor's uri.
  it( 'renders the Place Photo credit figcaption and its contributor link when a photo has attributions', async () => {
    const rec = installGoogleMaps( {
      photoAttributions: [ { displayName: 'Jane Contributor', uri: 'https://maps.google.com/maps/contrib/123' } ],
    } );
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } ) );
    const VayuLokLive = await loadComponent();

    const { container } = render( <VayuLokLive /> );
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    // Drive the real search -> select flow so the component resolves the Place and maps its
    // photos (with Google's authorAttributions) into previewPlace.photos.
    const input = screen.getByRole( 'combobox' );
    fireEvent.change( input, { target: { value: 'Mumbai' } } );
    const option = await screen.findByRole( 'option', { name: /Mumbai/i } );
    fireEvent.mouseDown( option );

    // The mandated attribution figcaption renders, carrying the contributor's name, and links
    // out to the contributor's Google uri (target _blank). This is what Google's ToS requires.
    const credit = await waitFor( () => {
      const el = container.querySelector( '.vl-live-photo-credit' );
      expect( el ).not.toBeNull();
      return el as HTMLElement;
    } );
    const link = credit.querySelector( 'a' ) as HTMLAnchorElement;
    expect( link ).not.toBeNull();
    expect( link.getAttribute( 'href' ) ).toBe( 'https://maps.google.com/maps/contrib/123' );
    expect( link.textContent ).toContain( 'Jane Contributor' );
  } );
} );
