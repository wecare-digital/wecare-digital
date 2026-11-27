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
  assert.match(server, /WEATHER_INSIGHTS_AGGREGATE_ENABLED/);
  assert.match(server, /aggregateComplete\(rows\[0\]/);
  assert.match(server, /if \(range !== '30d'\) \{[\s\S]*aggregateSql\(AGGREGATE_TABLE\)[\s\S]*\} else \{[\s\S]*weatherSql\(source\)/);
  assert.match(server, /HARD_MAX_BYTES_PER_QUERY = 1073741824n/);
  assert.match(server, /AGGREGATE_MAX_BYTES_BILLED = '134217728'/);
  assert.match(server, /error\.code = 'query_cost_cap_exceeded'/);
  assert.match(build, /--maximum_bytes_billed="\$CAP_BYTES"/);
  assert.match(build, /MAX_CHUNKS" -le 12/);
  assert.match(build, /NOT EXISTS/);
  assert.doesNotMatch(build, /gcloud[^\n]*quota|services quota|apply_quota/i);
});

test('aggregate query reads only the aggregate table and reports coverage', async () => {
  const { aggregateSql } = await import('../gcp/vayulok-weather-insights/aggregate.mjs');
  const sql = aggregateSql('p.d.weather_history_in_windows');
  assert.doesNotMatch(sql, /weather_history_in`/);
  assert.match(sql, /windows_loaded/);
  assert.match(sql, /window_end > @start_date/);
  for (const name of ['@lat', '@lng', '@start_date']) assert.ok(sql.includes(name), name);
});

test('aggregate is served only when it covers the requested range', async () => {
  const { aggregateComplete } = await import('../gcp/vayulok-weather-insights/aggregate.mjs');
  const today = '2026-11-27';
  const full = { first_window: { value: '2025-11-16' }, windows_loaded: 24 };
  assert.equal(aggregateComplete(full, '2025-11-27', today), true);
  // newest-first partial load: about four months of a 5y request
  assert.equal(aggregateComplete({ first_window: '2026-07-16', windows_loaded: 9 }, '2021-11-27', today), false);
  // reaches the start but has gaps
  assert.equal(aggregateComplete({ first_window: '2021-11-16', windows_loaded: 40 }, '2021-11-27', today), false);
  assert.equal(aggregateComplete({ first_window: '2021-11-16', windows_loaded: 118 }, '2021-11-27', today), true);
  // empty or malformed result fails closed
  assert.equal(aggregateComplete({ first_window: null, windows_loaded: 0 }, '2025-11-27', today), false);
  assert.equal(aggregateComplete(undefined, '2025-11-27', today), false);
});

test('aggregate builder marks empty windows and de-duplicates hourly rows', () => {
  const build = readFileSync(new URL('../scripts/build_weather_history_aggregate.sh', import.meta.url), 'utf8');
  assert.match(build, /sentinel_sql/);
  assert.match(build, /QUALIFY ROW_NUMBER\(\)/);
  assert.match(build, /C_TEMP="\$\{C_TEMP:-temperature_c\}"/);
  assert.match(build, /MAX_CHUNKS="\$\{MAX_CHUNKS:-4\}"/);
});


test('aggregate SQL rejects invalid table identifiers before interpolation', async () => {
  const { aggregateSql } = await import('../gcp/vayulok-weather-insights/aggregate.mjs');
  for (const table of [undefined, '', 'p.d.t`', 'p.d.t; SELECT 1', 'p.d.t\n', 'p.d']) {
    assert.throws(() => aggregateSql(table), /invalid_weather_insights_aggregate_table/);
  }
  assert.ok(aggregateSql('my-project.dataset.weather_history_in_windows').includes('my-project.dataset.weather_history_in_windows'));
});

test('container includes both historical helpers and long-range caps preserve stricter configuration', () => {
  const docker = readFileSync(new URL('../gcp/vayulok-weather-insights/Dockerfile', import.meta.url), 'utf8');
  const server = readFileSync(new URL('../gcp/vayulok-weather-insights/server.mjs', import.meta.url), 'utf8');
  assert.match(docker, /COPY package\.json server\.mjs weather-data\.mjs aggregate\.mjs \.\//);
  assert.match(server, /import \{ cleanSummary, decodeRows, parseNumber \} from '\.\/weather-data\.mjs'/);
  assert.match(server, /requested > 0n && requested < ceiling \? requested : ceiling/);
  assert.match(server, /boundedQueryBytes\(process\.env\.BQ_MAX_BYTES_BILLED_1Y \|\| GLOBAL_MAX_BYTES_BILLED, BigInt\(AGGREGATE_MAX_BYTES_BILLED\)\)/);
  assert.match(server, /boundedQueryBytes\(process\.env\.BQ_MAX_BYTES_BILLED_5Y \|\| GLOBAL_MAX_BYTES_BILLED, BigInt\(AGGREGATE_MAX_BYTES_BILLED\)\)/);
  assert.match(server, /\], RANGE_MAX_BYTES_BILLED\[range\]\);/);
});
