// Behavioural regression tests for the pure helpers extracted from
// src/components/VayuLokLive.tsx into the co-located sibling module
// src/components/VayuLokLive.helpers.ts during the Phase 3 structural refactor.
//
// The helpers module imports only TYPES from ./VayuLokLive.types (erased by the
// esbuild `tsx` transform), so it compiles and evaluates with no runtime import
// resolution. We load it through the shared offline loadTsxModule idiom (see
// tests/helpers/loadTsx.mjs) and assert the exact outputs of the pure functions.
// Inputs are fixed so there is no Date.now()/timezone nondeterminism.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadTsxModule } from './helpers/loadTsx.mjs';

function loadHelpers() {
  const { exports } = loadTsxModule( {
    file: 'src/components/VayuLokLive.helpers.ts',
    globals: { env: {} },
  } );
  return exports;
}

// --- aqiCategory (CPCB bands) ----------------------------------------------

// The helper runs in a node:vm context, so objects it returns carry that context's
// Object.prototype; assert on field values (not deepStrictEqual, which checks prototype
// identity across the vm boundary).
function assertBand( band, word, sev ) {
  assert.equal( band.word, word );
  assert.equal( band.sev, sev );
}

test( 'aqiCategory maps AQI values onto the CPCB band word + severity form', () => {
  const { aqiCategory } = loadHelpers();
  assertBand( aqiCategory( 0 ), 'Good', 'good' );
  assertBand( aqiCategory( 50 ), 'Good', 'good' );
  assertBand( aqiCategory( 51 ), 'Satisfactory', 'sat' );
  assertBand( aqiCategory( 100 ), 'Satisfactory', 'sat' );
  assertBand( aqiCategory( 200 ), 'Moderate', 'mod' );
  assertBand( aqiCategory( 300 ), 'Poor', 'poor' );
  assertBand( aqiCategory( 400 ), 'Very Poor', 'worst' );
  assertBand( aqiCategory( 401 ), 'Severe', 'worst' );
} );

// --- severityFromCategory (Google category text -> no-red band) -------------

test( 'severityFromCategory maps Google category text onto the no-red band', () => {
  const { severityFromCategory } = loadHelpers();
  assert.equal( severityFromCategory( 'Good air quality' ), 'good' );
  assert.equal( severityFromCategory( 'Excellent' ), 'good' );
  assert.equal( severityFromCategory( 'Moderate' ), 'mod' );
  assert.equal( severityFromCategory( 'Satisfactory' ), 'sat' );
  assert.equal( severityFromCategory( 'Low air quality' ), 'sat' );
  assert.equal( severityFromCategory( 'Unhealthy' ), 'poor' );
  assert.equal( severityFromCategory( 'Very poor' ), 'worst' );
  assert.equal( severityFromCategory( 'Hazardous' ), 'worst' );
  assert.equal( severityFromCategory( 'nonsense' ), null );
  assert.equal( severityFromCategory( undefined ), null );
} );

// --- formatPollutantValue (honest precision, no fabricated zero) -----------

test( 'formatPollutantValue preserves magnitude-aware precision', () => {
  const { formatPollutantValue } = loadHelpers();
  assert.equal( formatPollutantValue( 0 ), '0' );
  assert.equal( formatPollutantValue( 32 ), '32' );
  assert.equal( formatPollutantValue( 32.6 ), '33' );
  assert.equal( formatPollutantValue( 0.4 ), '0.4' );
  assert.equal( formatPollutantValue( 0.04 ), '0.04' );
  assert.equal( formatPollutantValue( Number.NaN ), '' );
} );

// --- routeDurationLabel / routeDistanceLabel -------------------------------

test( 'routeDurationLabel renders hr/min combinations', () => {
  const { routeDurationLabel } = loadHelpers();
  assert.equal( routeDurationLabel( 0 ), '1 min' );
  assert.equal( routeDurationLabel( 600 ), '10 min' );
  assert.equal( routeDurationLabel( 3600 ), '1 hr' );
  assert.equal( routeDurationLabel( 3900 ), '1 hr 5 min' );
} );

test( 'routeDistanceLabel switches from metres to kilometres', () => {
  const { routeDistanceLabel } = loadHelpers();
  assert.equal( routeDistanceLabel( 450 ), '450 m' );
  assert.equal( routeDistanceLabel( 1500 ), '1.5 km' );
  assert.equal( routeDistanceLabel( 250000 ), '250 km' );
} );

// --- windDirection / concUnitLabel / windUnitLabel -------------------------

test( 'windDirection maps compass degrees onto 8-point labels', () => {
  const { windDirection } = loadHelpers();
  assert.equal( windDirection( 0 ), 'N' );
  assert.equal( windDirection( 90 ), 'E' );
  assert.equal( windDirection( 180 ), 'S' );
  assert.equal( windDirection( 270 ), 'W' );
  assert.equal( windDirection( 45 ), 'NE' );
} );

test( 'concUnitLabel / windUnitLabel shorten the API enums', () => {
  const { concUnitLabel, windUnitLabel } = loadHelpers();
  assert.equal( concUnitLabel( 'PARTS_PER_BILLION' ), 'ppb' );
  assert.equal( concUnitLabel( 'MICROGRAMS_PER_CUBIC_METER' ), '\u00B5g/m\u00B3' );
  assert.equal( concUnitLabel( undefined ), '' );
  assert.equal( windUnitLabel( 'MILES_PER_HOUR' ), 'mph' );
  assert.equal( windUnitLabel( undefined ), 'km/h' );
} );

// --- directDistanceKm (great-circle distance) ------------------------------

test( 'directDistanceKm computes a sane great-circle distance', () => {
  const { directDistanceKm } = loadHelpers();
  // New Delhi -> London is roughly 6700 km.
  const km = directDistanceKm(
    { name: 'A', addr: '', lat: 28.6139, lng: 77.2090 },
    { name: 'B', addr: '', lat: 51.5072, lng: -0.1276 },
  );
  assert.ok( km > 6600 && km < 6800, `expected ~6700 km, got ${ km }` );
  // Identical points are zero distance.
  const same = directDistanceKm(
    { name: 'A', addr: '', lat: 10, lng: 20 },
    { name: 'A', addr: '', lat: 10, lng: 20 },
  );
  assert.ok( same < 1e-6 );
} );

// --- airStateFromApiData (currentConditions parse, drops bad data) ---------

test( 'airStateFromApiData parses a currentConditions payload and derives the band', () => {
  const { airStateFromApiData } = loadHelpers();
  const out = airStateFromApiData( {
    dateTime: '2024-03-04T16:00:00.000Z',
    regionCode: 'IN',
    indexes: [
      { code: 'ind_cpcb', aqi: 72, category: 'Satisfactory', displayName: 'CPCB', dominantPollutant: 'pm25' },
      { code: 'uaqi', aqi: 55, category: 'Moderate' },
    ],
    pollutants: [
      { code: 'pm25', displayName: 'PM2.5', concentration: { value: 18.2, units: 'MICROGRAMS_PER_CUBIC_METER' } },
    ],
  } );
  assert.ok( out );
  assert.equal( out.aqi, 72 );
  assert.equal( out.word, 'Satisfactory' );
  assert.equal( out.sev, 'sat' );
  assert.equal( out.indexCode, 'ind_cpcb' );
  assert.equal( out.regionCode, 'IN' );
  assert.equal( out.pollutants.length, 1 );
  assert.equal( out.pollutants[ 0 ].unit, '\u00B5g/m\u00B3' );
} );

test( 'airStateFromApiData returns null when no finite AQI is present', () => {
  const { airStateFromApiData } = loadHelpers();
  assert.equal( airStateFromApiData( null ), null );
  assert.equal( airStateFromApiData( { indexes: [] } ), null );
  assert.equal( airStateFromApiData( { indexes: [ { code: 'x', aqi: 'nope' } ] } ), null );
} );
