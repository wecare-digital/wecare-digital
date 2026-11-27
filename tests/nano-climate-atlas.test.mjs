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

test( 'Nano Climate keeps the original shared visual system in every build', () => {
  const page = source( 'pages/atmos/nano-climate.tsx' );
  const live = source( 'components/VayuLokLive.tsx' );
  assert.ok( page.includes( 'badgeLabel="Nano Climate by WECARE.DIGITAL"' ) );
  assert.ok( page.includes( 'words={ cycleWords }' ) );
  assert.ok( page.includes( 'pillKey={ mode }' ) );
  assert.ok( page.includes( '<VayuLokApprovedGlobe' ) );
  assert.ok( page.includes( '<RotatingHero' ) );
  assert.ok( page.includes( 'atlas={ atlasEnabled }' ) );
  assert.doesNotMatch( page, /atlasEnabled\s*\?|vl-atlas-page-head/ );
  assert.doesNotMatch( live, /data-atlas=|vl-atlas-|vl-live-map-contents/ );
  assert.ok( live.includes( 'className="vl-live-air-toggle"' ) );
  assert.ok( live.includes( 'className="vl-live-tools"' ) );
  assert.ok( live.includes( '.vl-live-air-pollutants,.vl-live-air-heatmap,.vl-live-air-forecast,.vl-live-air-health,.vl-live-air-history{margin-top:var(--vl-section-gap);padding-top:var(--vl-section-pad);border-top:1px solid var(--hair)}' ) );
  assert.ok( live.includes( 'padding-inline-start:10px;border-inline-start:3px solid var(--lime)' ) );
  assert.ok( live.includes( '<VayuLokWeatherInsights\n                          lat={ place.lat }' ) );
  assert.ok( live.includes( 'resetAtlasLocationReadings();\n    setPlace( next );' ) );
  assert.equal( ( live.match( /ref=\{ mapHost \}/g ) || [] ).length, 1 );
});
