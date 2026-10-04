import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SITE_ORIGIN } from '../config/share';

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
}

// Optional author attribution Google supplies with a Place photo. When provided, the
// stubbed search prediction resolves to a Place carrying one photo with these
// attributions, so the component's mandated-attribution rendering can be exercised.
interface PhotoAttribution { displayName?: string; uri?: string }
interface InstallOpts { paintMap?: boolean; photoAttributions?: PhotoAttribution[] }

function installGoogleMaps( opts: boolean | InstallOpts = true ): MapsRecorder {
  const { paintMap = true, photoAttributions }: InstallOpts =
    typeof opts === 'boolean' ? { paintMap: opts } : opts;
  const rec: MapsRecorder = {
    mapOpts: null,
    overlayPushes: [],
    overlayClears: 0,
    imageMapTypeOpts: [],
    geocodeCalls: [],
    autocompleteCalls: [],
    placeFetchFields: [],
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
    geocode( req: Record<string, unknown> ) { rec.geocodeCalls.push( req ); }
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

  ( window as unknown as { google: unknown } ).google = {
    maps: {
      Map: FakeMap,
      Marker: FakeMarker,
      Geocoder: FakeGeocoder,
      ImageMapType: FakeImageMapType,
      LatLng: class { constructor( _a: number, _b: number ) { /* no-op */ } },
      places,
      importLibrary: async ( name: string ) => name === 'places'
        ? places
        : name === 'maps'
          ? { Map: FakeMap }
          : name === 'marker'
            ? { Marker: FakeMarker }
            : {},
    },
  };

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
  vi.useRealTimers();
} );

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

  it( 'does NOT request a heatmap overlay on load, and only pushes one after a layer click', async () => {
    const fetchSpy = vi.fn().mockResolvedValue( { ok: false, json: async () => ( {} ) } );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();

    render( <VayuLokLive /> );
    // Wait for the map to initialise (mapReady flips via requestAnimationFrame).
    await waitFor( () => expect( rec.mapOpts ).not.toBeNull() );

    // On load: no overlay pushed, and no ImageMapType (hence no heatmapTiles getTileUrl) created.
    expect( rec.overlayPushes ).toHaveLength( 0 );
    expect( rec.imageMapTypeOpts ).toHaveLength( 0 );
    // No fetch has hit the airquality heatmapTiles endpoint either.
    const hitHeatmapTiles = () => fetchSpy.mock.calls.some(
      c => String( c[ 0 ] ).includes( 'airquality.googleapis.com' ) && String( c[ 0 ] ).includes( 'heatmapTiles' )
    );
    expect( hitHeatmapTiles() ).toBe( false );

    // The map object is constructed before the tilesloaded callback flips mapReady.
    // Wait for the ready-only controls rather than racing that paint lifecycle.
    await waitFor( () => expect( screen.getByRole( 'button', { name: 'AQI' } ) ).toBeInTheDocument() );

    // Press the AQI layer control.
    fireEvent.click( screen.getByRole( 'button', { name: 'AQI' } ) );

    // NOW an overlay is pushed and an ImageMapType is created, deferred to the click.
    await waitFor( () => expect( rec.overlayPushes ).toHaveLength( 1 ) );
    expect( rec.imageMapTypeOpts ).toHaveLength( 1 );

    // Req 05: the overlay carries the fully-translucent lime wiring. The ImageMapType is
    // constructed with a low `opacity` so the geo/road map stays visible underneath; the
    // lime recolour itself is a scoped CSS filter the live tiles receive (not asserted by
    // brittle numeric filter values). Assert the opacity option is present and translucent.
    const opacity = rec.imageMapTypeOpts[ 0 ].opacity as number;
    expect( typeof opacity ).toBe( 'number' );
    expect( opacity ).toBeGreaterThan( 0 );
    expect( opacity ).toBeLessThan( 1 );

    // The overlay's tile URL points at the air-quality heatmapTiles SKU (built lazily per tile),
    // and uses a VALID Air Quality API mapType. The AQI layer must use the universal UAQI scale
    // (not US_AQI) so the heatmap matches the India-CPCB legend/panels on the page. The mapType
    // sits in the path segment immediately before /heatmapTiles/.
    const getTileUrl = rec.imageMapTypeOpts[ 0 ].getTileUrl as ( c: { x: number; y: number }, z: number ) => string;
    const url = getTileUrl( { x: 1, y: 2 }, 3 );
    expect( url ).toContain( 'airquality.googleapis.com' );
    expect( url ).toContain( 'heatmapTiles' );
    const aqiType = url.match( /\/mapTypes\/([^/]+)\/heatmapTiles\// )?.[ 1 ];
    expect( aqiType ).toBe( 'UAQI_RED_GREEN' );
    expect( aqiType ).not.toBe( 'US_AQI' );

    // Switching to the PM2.5 layer must use a VALID PM2.5 mapType. PM25_HEATMAP is not in the
    // API enum and would 400/render nothing; PM25_INDIGO_PERSIAN is the correct token.
    fireEvent.click( screen.getByRole( 'button', { name: 'PM2.5' } ) );
    await waitFor( () => expect( rec.imageMapTypeOpts ).toHaveLength( 2 ) );
    const getPm25TileUrl = rec.imageMapTypeOpts[ 1 ].getTileUrl as ( c: { x: number; y: number }, z: number ) => string;
    const pm25Type = getPm25TileUrl( { x: 1, y: 2 }, 3 ).match( /\/mapTypes\/([^/]+)\/heatmapTiles\// )?.[ 1 ];
    expect( pm25Type ).toBe( 'PM25_INDIGO_PERSIAN' );
    expect( pm25Type ).not.toBe( 'PM25_HEATMAP' );
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

    // Switching to PM2.5 swaps the left-card result to the PM2.5-focused block.
    fireEvent.click( screen.getByRole( 'button', { name: 'PM2.5' } ) );
    await waitFor( () => {
      const pm25Result = container.querySelector( '.vl-live-left .vl-live-layer-result' ) as HTMLElement;
      expect( pm25Result.textContent ).toContain( 'PM2.5 heatmap result' );
      expect( pm25Result.textContent ).toContain( '82' );
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
} );

describe( 'VayuLokLive - forecast, history and partial failure rendering', () => {
  beforeEach( () => {
    vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', DUMMY_KEY );
    installGoogleMaps();
  } );

  const response = ( body: unknown, ok = true ) => Promise.resolve( {
    ok,
    json: async () => body,
  } as Response );

  it( 'renders 24h combined intelligence, 10-day outlook and history when Google endpoints return data', async () => {
    const base = Date.now() + 60 * 60 * 1000;
    const fetchSpy = vi.fn( ( input: RequestInfo | URL ) => {
      const url = String( input );
      if ( url.includes( 'weather.googleapis.com/v1/currentConditions' ) ) {
        return response( {
          currentTime: new Date().toISOString(),
          temperature: { degrees: 30 },
          feelsLikeTemperature: { degrees: 33 },
          relativeHumidity: 64,
          wind: { speed: { value: 12, unit: 'KILOMETERS_PER_HOUR' }, direction: { degrees: 90 }, gust: { value: 20 } },
          weatherCondition: { description: { text: 'Clear' } },
          precipitation: { probability: { percent: 20 }, qpf: { quantity: 0.4 } },
          uvIndex: 6,
          visibility: { distance: 8 },
          airPressure: { meanSeaLevelMillibars: 1007 },
          dewPoint: { degrees: 23 },
          heatIndex: { degrees: 35 },
          wetBulbTemperature: { degrees: 25 },
          cloudCover: 25,
        } );
      }
      if ( url.includes( 'airquality.googleapis.com/v1/currentConditions' ) ) {
        return response( {
          dateTime: new Date().toISOString(),
          indexes: [ { code: 'ind_cpcb', aqi: 120, category: 'Moderate', dominantPollutant: 'pm25' } ],
          pollutants: [ { code: 'pm25', concentration: { value: 58, units: 'MICROGRAMS_PER_CUBIC_METER' } } ],
          healthRecommendations: { generalPopulation: 'Reduce prolonged exertion if you feel symptoms.' },
        } );
      }
      if ( url.includes( 'weather.googleapis.com/v1/forecast/hours' ) ) {
        const secondPage = url.includes( 'pageToken=page-2' );
        const start = secondPage ? 24 : 0;
        return response( {
          forecastHours: Array.from( { length: 24 }, ( _, i ) => {
            const offset = start + i;
            return {
              interval: { startTime: new Date( base + offset * 3600000 ).toISOString() },
              temperature: { degrees: 30 - Math.floor( offset / 8 ) },
              precipitation: { probability: { percent: 20 + ( offset % 6 ) * 5 } },
              uvIndex: 5,
              weatherCondition: { description: { text: 'Clear' } },
            };
          } ),
          ...( secondPage ? {} : { nextPageToken: 'page-2' } ),
        } );
      }
      if ( url.includes( 'weather.googleapis.com/v1/forecast/days' ) ) {
        return response( {
          forecastDays: [ {
            displayDate: { year: 2026, month: 10, day: 4 },
            minTemperature: { degrees: 23 },
            maxTemperature: { degrees: 32 },
            daytimeForecast: { precipitation: { probability: { percent: 30 } }, weatherCondition: { description: { text: 'Partly cloudy' } } },
            sunEvents: { sunriseTime: '2026-10-04T00:05:00Z', sunsetTime: '2026-10-04T11:45:00Z' },
          } ],
        } );
      }
      if ( url.includes( 'weather.googleapis.com/v1/history/hours' ) ) {
        return response( {
          historyHours: [ {
            interval: { startTime: new Date( Date.now() - 3600000 ).toISOString() },
            temperature: { degrees: 28 },
            precipitation: { probability: { percent: 10 } },
            weatherCondition: { description: { text: 'Clear' } },
          } ],
        } );
      }
      if ( url.includes( 'weather.googleapis.com/v1/publicAlerts' ) ) return response( { weatherAlerts: [] } );
      if ( url.includes( 'airquality.googleapis.com/v1/forecast' ) ) {
        return response( {
          hourlyForecasts: [ 0, 1 ].map( offset => ( {
            dateTime: new Date( base + offset * 3600000 ).toISOString(),
            indexes: [ { code: 'ind_cpcb', aqi: 110 + offset * 4, category: 'Moderate' } ],
            pollutants: [ { code: 'pm25', concentration: { value: 50 + offset } } ],
          } ) ),
        } );
      }
      if ( url.includes( 'airquality.googleapis.com/v1/history' ) ) {
        return response( {
          hoursInfo: [ {
            dateTime: new Date( Date.now() - 3600000 ).toISOString(),
            indexes: [ { code: 'ind_cpcb', aqi: 125, category: 'Moderate' } ],
            pollutants: [ { code: 'pm25', concentration: { value: 60 } } ],
          } ],
        } );
      }
      if ( url.includes( 'pollen.googleapis.com' ) ) return response( { dailyInfo: [] } );
      return response( {}, false );
    } );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );

    expect( await screen.findByRole( 'heading', { name: 'Next 24 hours' } ) ).toBeInTheDocument();
    expect( await screen.findByText( '48-hour weather' ) ).toBeInTheDocument();
    expect( await screen.findByText( '10-day outlook' ) ).toBeInTheDocument();
    expect( await screen.findByText( 'Past 24 hours' ) ).toBeInTheDocument();
    expect( await screen.findByRole( 'heading', { name: 'Air intelligence' } ) ).toBeInTheDocument();
    expect( await screen.findByText( '96-hour AQ forecast' ) ).toBeInTheDocument();
    expect( screen.getByText( 'Best outside' ) ).toBeInTheDocument();
  } );

  it( 'keeps Weather visible when the Air current endpoint fails', async () => {
    const fetchSpy = vi.fn( ( input: RequestInfo | URL ) => {
      const url = String( input );
      if ( url.includes( 'weather.googleapis.com/v1/currentConditions' ) ) {
        return response( {
          currentTime: new Date().toISOString(),
          temperature: { degrees: 31 },
          feelsLikeTemperature: { degrees: 34 },
          weatherCondition: { description: { text: 'Sunny' } },
        } );
      }
      return response( {}, false );
    } );
    vi.stubGlobal( 'fetch', fetchSpy );
    const VayuLokLive = await loadComponent();
    render( <VayuLokLive /> );

    expect( ( await screen.findAllByText( '31°' ) ).length ).toBeGreaterThan( 0 );
    expect( screen.getAllByText( 'Sunny' ).length ).toBeGreaterThan( 0 );
    expect( screen.queryByText( 'Current conditions are temporarily unavailable.' ) ).toBeNull();
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
