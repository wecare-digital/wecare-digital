import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTsxModule } from './helpers/loadTsx.mjs';

const { exports: { formatEnvironmentSections, isBuildingCandidate } } = loadTsxModule({
  file: 'src/components/VayuLokEnvironmentData.ts',
  globals: { require: name => name.includes('constants') ? { API_BASE: 'https://unit-test.invalid' } : {} },
});

test('new sources retain missing, zero and historical semantics', () => {
  const items = formatEnvironmentSections({sources:{
    elevation:{status:'ok',elevationM:0},
    cpcb:{status:'ok',station:'Test',readings:[{pollutant:'PM2.5',average:0,observedAt:'2026-11-27T14:00:00+05:30'}]},
    pvgis:{status:'disabled'},
    solar:{status:'budget_limited'},
    spartan:{status:'ok',site:'Delhi',pm25UgM3:41.52,endDate:'2024-03-06',method:'filter'},
  }});
  assert.equal(items.length,4);
  assert.equal(items[0].rows[0].value,'0 m');
  assert.ok(items[1].rows.some(x=>x.value==='0 (source unit not specified)'));
  assert.equal(items[2].rows.length,0);
  assert.match(items[2].note,/budget/);
  assert.match(items[3].note,/Historical scientific/);
  assert.ok(items[3].rows.some(x=>x.value==='2024-03-06'));
});

test('only precise positive-area viewports trigger automatic building lookup', () => {
  assert.equal(isBuildingCandidate(undefined),false);
  assert.equal(isBuildingCandidate({north:29,south:28,east:78,west:77}),false);
  assert.equal(isBuildingCandidate({north:28.601,south:28.6,east:77.201,west:77.2}),true);
  assert.equal(isBuildingCandidate({north:28.6,south:28.6,east:77.2,west:77.2}),false);
});

test('source addition preserves the shared hero and original map design', () => {
  const page=readFileSync(new URL('../src/pages/atmos/nano-climate.tsx',import.meta.url),'utf8');
  const live=readFileSync(new URL('../src/components/VayuLokLive.tsx',import.meta.url),'utf8');
  assert.match(page, /badgeLabel="Nano Climate by WECARE.DIGITAL"/);
  assert.match(page, /words=\{ cycleWords \}/);
  assert.match(page, /<VayuLokApprovedGlobe/);
  assert.doesNotMatch(page, /atlasEnabled\s*\?|vl-atlas-page-head/);
  assert.ok(live.includes('padding-inline-start:10px;border-inline-start:3px solid var(--lime)'));
  assert.equal((live.match(/ref=\{ mapHost \}/g)||[]).length,1);
  assert.match(live, /useVayuLokEnvironmentData/);
});

test('environment cards are keyed to the selected coordinates so a new search never shows older place data', () => {
  const source=readFileSync(new URL('../src/components/VayuLokEnvironmentData.ts',import.meta.url),'utf8');
  assert.match(source, /const key = active \? \[lat, lng, region, building\]\.join\( ':' \)/);
  assert.match(source, /result\?\.key === key \? result\.data : loading/);
  assert.match(source, /envelope\.latitude !== lat \|\| envelope\.longitude !== lng/);
  assert.match(source, /controller\.abort\(\)/);
});

test('historical weather 1y and 5y read a bounded aggregate and never scan the raw table', () => {
  const server=readFileSync(new URL('../gcp/vayulok-weather-insights/server.mjs',import.meta.url),'utf8');
  const build=readFileSync(new URL('../scripts/build_weather_history_aggregate.sh',import.meta.url),'utf8');
  assert.match(server, /if \(range !== '30d'\) \{[\s\S]*aggregateSql\(AGGREGATE_TABLE\)[\s\S]*\} else \{[\s\S]*weatherSql\(source\)/);
  assert.match(server, /HARD_MAX_BYTES_PER_QUERY = 1073741824n/);
  assert.match(server, /AGGREGATE_MAX_BYTES_BILLED = '134217728'/);
  assert.match(server, /error\.code = 'query_cost_cap_exceeded'/);
  assert.match(build, /--maximum_bytes_billed="\$CAP_BYTES"/);
  assert.match(build, /MAX_CHUNKS" -le 12/);
  assert.match(build, /NOT EXISTS/);
  assert.doesNotMatch(build, /gcloud[^\n]*quota|services quota|apply_quota/i);
});
