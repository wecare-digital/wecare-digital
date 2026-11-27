import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanSummary, decodeRows, parseNumber } from '../gcp/vayulok-weather-insights/weather-data.mjs';

test('BigQuery repeated RECORD values decode to an array, retaining null and zero', () => {
  const schema = { fields: [
    { name: 'sample_hours', type: 'INTEGER' },
    { name: 'mean_temperature_c', type: 'FLOAT' },
    { name: 'precipitation_mm', type: 'FLOAT' },
    { name: 'monthly', type: 'RECORD', mode: 'REPEATED', fields: [
      { name: 'month', type: 'INTEGER' },
      { name: 'mean_temperature_c', type: 'FLOAT' },
      { name: 'precipitation_mm', type: 'FLOAT' },
      { name: 'mean_humidity_pct', type: 'FLOAT' },
    ] },
  ] };
  const rows = [{ f: [{ v: '2' }, { v: null }, { v: '0' }, { v: [
    { v: { f: [{ v: '1' }, { v: null }, { v: '0' }, { v: null }] } },
    { v: { f: [{ v: '2' }, { v: '-2.5' }, { v: null }, { v: '50' }] } },
  ] }] }];
  const [row] = decodeRows({ schema, rows });
  assert.ok(Array.isArray(row.monthly));
  const summary = cleanSummary(row, '30d');
  assert.equal(summary.meanTemperatureC, null);
  assert.equal(summary.precipitationMm, 0);
  assert.equal(summary.meanHumidityPct, null);
  assert.deepEqual(summary.monthly, [
    { month: 1, meanTemperatureC: null, precipitationMm: 0, meanHumidityPct: null },
    { month: 2, meanTemperatureC: -2.5, precipitationMm: null, meanHumidityPct: 50 },
  ]);
});

test('missing, blank and malformed numbers cannot become environmental readings', () => {
  const summary = cleanSummary({ sample_hours: 1, grid_distance_km: 0,
    mean_temperature_c: '', min_temperature_c: null, max_temperature_c: 0,
    precipitation_mm: false, mean_humidity_pct: 'not a number',
    monthly: [null, { month: 13, mean_temperature_c: 2 }] }, '1y');
  assert.equal(summary.gridDistanceKm, 0);
  assert.equal(summary.meanTemperatureC, null);
  assert.equal(summary.minTemperatureC, null);
  assert.equal(summary.maxTemperatureC, 0);
  assert.equal(summary.precipitationMm, null);
  assert.equal(summary.meanHumidityPct, null);
  assert.deepEqual(summary.monthly, []);
  assert.equal(cleanSummary({ sample_hours: 0 }, '5y'), null);
  assert.equal(cleanSummary({ sample_hours: null }, '5y'), null);
});

test('coordinates reject missing, blank and invalid input but retain legitimate zero', () => {
  for (const value of [null, undefined, '', '  ', false, 'NaN', '91']) {
    assert.equal(parseNumber(value, -90, 90), null);
  }
  assert.equal(parseNumber('0', -90, 90), 0);
  assert.equal(parseNumber('28.6', -90, 90), 28.6);
});
