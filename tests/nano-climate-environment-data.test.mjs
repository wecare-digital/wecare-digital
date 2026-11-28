import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
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
  assert.match(sql, /window_starts/);
  assert.match(sql, /window_end > @start_date/);
  for (const name of ['@lat', '@lng', '@start_date']) assert.ok(sql.includes(name), name);
});

test('expectedWindows lists every half-month window with a 16 day lag', async () => {
  const { expectedWindows } = await import('../gcp/vayulok-weather-insights/aggregate.mjs');
  assert.deepEqual(expectedWindows('2026-08-01', '2026-11-27'), [
    '2026-08-01', '2026-08-16', '2026-09-01', '2026-09-16', '2026-10-01', '2026-10-16',
  ]);
  // a start inside a window excludes that partial window
  assert.equal(expectedWindows('2026-08-10', '2026-11-27')[0], '2026-08-16');
  // a December window ends on 1 January
  assert.ok(expectedWindows('2025-12-01', '2026-03-01').includes('2025-12-16'));
  assert.equal(expectedWindows('2021-11-27', '2026-11-27').length, 118);
});

test('aggregate is served only when every expected window is loaded', async () => {
  const { aggregateComplete, expectedWindows } = await import('../gcp/vayulok-weather-insights/aggregate.mjs');
  const today = '2026-11-27';
  const start = '2021-11-27';
  const all = expectedWindows(start, today);
  assert.equal(aggregateComplete({ window_starts: all }, start, today), true);
  // BigQuery DATE values may arrive as plain strings or objects
  assert.equal(aggregateComplete({ window_starts: all.map((value) => ({ value })) }, start, today), true);
  // a single missing window in the middle is rejected (no tolerance)
  const gap = all.filter((_, i) => i !== 40);
  assert.equal(aggregateComplete({ window_starts: gap }, start, today), false);
  // newest-first partial load
  assert.equal(aggregateComplete({ window_starts: all.slice(-9) }, start, today), false);
  // extra older windows do not mask a missing one
  assert.equal(aggregateComplete({ window_starts: ['2020-01-01', ...gap] }, start, today), false);
  // empty or malformed result fails closed
  assert.equal(aggregateComplete({ window_starts: [] }, start, today), false);
  assert.equal(aggregateComplete({ window_starts: null }, start, today), false);
  assert.equal(aggregateComplete(undefined, start, today), false);
});

test('coveragePartial flags observed data that starts late', async () => {
  const { coveragePartial } = await import('../gcp/vayulok-weather-insights/aggregate.mjs');
  assert.equal(coveragePartial('2021-12-05T00:00:00Z', '2021-11-27'), false);
  assert.equal(coveragePartial('2024-03-01T00:00:00Z', '2021-11-27'), true);
  assert.equal(coveragePartial(null, '2021-11-27'), true);
});

test('server exposes coverage fields and the widget renders the partial flag', () => {
  const server = readFileSync(new URL('../gcp/vayulok-weather-insights/server.mjs', import.meta.url), 'utf8');
  assert.match(server, /coverage_start: summary\.coverageStart/);
  assert.match(server, /coveragePartial: range === '30d' \? false : coveragePartial\(/);
  const ui = readFileSync(new URL('../src/components/VayuLokWeatherInsights.tsx', import.meta.url), 'utf8');
  assert.match(ui, /data\.coveragePartial/);
});

test('aggregate builder --verify enforces completeness and raw equality (mocked bq)', () => {
  const dir = mkdtempSync(join(tmpdir(), 'fakebq-'));
  const script = fileURLToPath(new URL('../scripts/build_weather_history_aggregate.sh', import.meta.url));
  writeFileSync(join(dir, 'bq'), `#!/usr/bin/env bash
args="$*"
case "$args" in *"show "*) exit 0;; esac
case "$args" in
  *"SELECT CAST(window_start AS STRING) FROM"*) echo window_start; printf '%s\\n' $FAKE_DONE;;
  *"MAX(window_start) AS STRING"*) echo "a,b"; echo "2026-11-01,2026-11-16";;
  *"FROM h"*) echo c; echo "10,100,500.5,20.25";;
  *"COUNT(DISTINCT CONCAT"*"window_start = DATE"*) echo c; echo "$FAKE_AGG";;
  *) echo "{}";;
esac
`, { mode: 0o755 });
  const today = new Date();
  const done = [];
  for (let y = today.getUTCFullYear() - 5, m = 1; y < today.getUTCFullYear() + 1; m++) {
    if (m === 13) { y++; m = 1; }
    for (const d of [1, 16]) done.push(`${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`);
  }
  const run = (env) => spawnSync('bash', [script, '--verify'], {
    env: { ...process.env, AGGREGATE_DATASET: 'nano_climate_test', PATH: `${dir}:${process.env.PATH}`, ...env }, encoding: 'utf8',
  });
  try {
    const ok = run({ FAKE_DONE: done.join(' '), FAKE_AGG: '10,100,500.5,20.25' });
    assert.equal(ok.status, 0, ok.stdout + ok.stderr);
    assert.match(ok.stdout, /aggregate matches raw/);
    const bad = run({ FAKE_DONE: done.join(' '), FAKE_AGG: '10,100,999,20.25' });
    assert.notEqual(bad.status, 0);
    assert.match(bad.stdout, /aggregate differs from raw/);
    const missing = run({ FAKE_DONE: done.filter((_, i) => i !== 30).join(' '), FAKE_AGG: '10,100,500.5,20.25' });
    assert.notEqual(missing.status, 0);
    assert.match(missing.stdout, /missing windows/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('aggregate builder marks empty windows and de-duplicates hourly rows', () => {
  const build = readFileSync(new URL('../scripts/build_weather_history_aggregate.sh', import.meta.url), 'utf8');
  assert.match(build, /sentinel_sql/);
  assert.match(build, /QUALIFY ROW_NUMBER\(\)/);
  assert.match(build, /C_TEMP="\$\{C_TEMP:-temperature_c\}"/);
  assert.match(build, /MAX_CHUNKS="\$\{MAX_CHUNKS:-4\}"/);
});


test('builder requires an explicit writable aggregate dataset and refuses weather_insights', () => {
  const script = fileURLToPath(new URL('../scripts/build_weather_history_aggregate.sh', import.meta.url));
  const dir = mkdtempSync(join(tmpdir(), 'bqmock-'));
  const log = join(dir, 'calls.log');
  writeFileSync(join(dir, 'bq'), `#!/bin/sh\necho "$@" >> "${log}"\nexit 0\n`, { mode: 0o755 });
  const run = (args, extra = {}) => {
    const env = { ...process.env, PATH: `${dir}:${process.env.PATH}`, ...extra };
    delete env.AGGREGATE_DATASET;
    return spawnSync('bash', [script, ...args], { env: { ...env, ...extra }, encoding: 'utf8' });
  };
  try {
    let r = run([]);
    assert.equal(r.status, 2);
    assert.match(r.stdout, /set AGGREGATE_DATASET/);
    r = run(['--apply'], { AGGREGATE_DATASET: 'weather_insights' });
    assert.equal(r.status, 2);
    assert.match(r.stdout, /read-only/);
    r = run(['--apply', '--aggregate-dataset', 'Weather_Insights']);
    assert.equal(r.status, 2);
    r = run(['--aggregate-dataset', 'bad;name']);
    assert.equal(r.status, 2);
    assert.throws(() => readFileSync(log, 'utf8'), /ENOENT/, 'bq must never be called');
  } finally { rmSync(dir, { recursive: true, force: true }); }
  const build = readFileSync(script, 'utf8');
  assert.doesNotMatch(build, /bq\s+mk/);
  assert.match(build, /AGG="\$\{PROJECT\}\.\$\{AGGREGATE_DATASET\}\.weather_history_in_windows"/);
  assert.match(build, /RAW="\$\{PROJECT\}\.\$\{SOURCE_DATASET\}\.weather_history_in"/);
});

test('server aggregate table has no default and rejects the read-only dataset', async () => {
  const { writableAggregateTable } = await import('../gcp/vayulok-weather-insights/aggregate.mjs');
  assert.equal(writableAggregateTable(undefined), '');
  assert.equal(writableAggregateTable(''), '');
  assert.equal(writableAggregateTable('wecaredigitalbw.weather_insights.weather_history_in_windows'), '');
  assert.equal(writableAggregateTable('wecaredigitalbw.Weather_Insights.t'), '');
  assert.equal(writableAggregateTable('p.d.t`'), '');
  assert.equal(writableAggregateTable('wecaredigitalbw.nano_climate.weather_history_in_windows'), 'wecaredigitalbw.nano_climate.weather_history_in_windows');
  const server = readFileSync(new URL('../gcp/vayulok-weather-insights/server.mjs', import.meta.url), 'utf8');
  assert.match(server, /writableAggregateTable\(process\.env\.WEATHER_INSIGHTS_AGGREGATE_TABLE\)/);
  assert.doesNotMatch(server, /weather_insights\.weather_history_in_windows/);
  assert.match(server, /!AGGREGATE_ENABLED \|\| !AGGREGATE_TABLE/);
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
