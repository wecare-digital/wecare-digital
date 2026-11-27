import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTsxModule } from './helpers/loadTsx.mjs';
const { exports: { clampAtlasIndex } } = loadTsxModule( { file: 'src/lib/nanoClimateAtlas.ts' } );
const source = path => readFileSync( new URL( '../src/' + path, import.meta.url ), 'utf8' );

test( 'Atlas time inspection stays within real provider rows', () => {
  assert.equal( clampAtlasIndex( 0, 0, false ), null );
  assert.equal( clampAtlasIndex( 3, null, false ), 0 );
  assert.equal( clampAtlasIndex( 3, null, true ), 2 );
  assert.equal( clampAtlasIndex( 3, -5, false ), 0 );
  assert.equal( clampAtlasIndex( 3, 200, true ), 2 );
  assert.equal( clampAtlasIndex( 3, NaN, true ), 2 );
  assert.equal( clampAtlasIndex( 3, 1.8, false ), 1 );
});

test( 'Atlas is opt-in and uses existing provider-backed controls', () => {
  const page = source( 'pages/atmos/nano-climate.tsx' );
  const live = source( 'components/VayuLokLive.tsx' );
  assert.ok( page.includes( "process.env.NEXT_PUBLIC_NANO_CLIMATE_ATLAS === 'true'" ) );
  assert.ok( page.includes( 'atlas={ atlasEnabled }' ) );
  assert.ok( page.includes( '<VayuLokApprovedGlobe' ) );
  assert.ok( live.includes( 'setLayer( next )' ) );
  assert.ok( live.includes( 'airForecast.slice( 0, airForecastHours ) : airHistory' ) );
  assert.ok( live.includes( 'weatherHourly.slice( 0, weatherHours ) : weatherHistory' ) );
  assert.ok( live.includes( 'Time controls inspect location readings; the map shows current available layers.' ) );
  assert.ok( live.includes( '<VayuLokWeatherInsights\n                          lat={ place.lat }' ) );
  assert.ok( live.includes( 'resetAtlasLocationReadings();\n    setPlace( next );' ) );
});
