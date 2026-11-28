// Pure helpers for the pre-aggregated 1y/5y historical weather summary. Kept apart
// from server.mjs so the SQL shape and completeness rules can be tested directly.

const DAY_MS = 86400000;
// Windows are half months: [1st, 16th) and [16th, 1st of next month). Only windows
// that start on or after the range start are required, and the newest window may lag
// by up to LAG_DAYS because the builder loads windows only after they have ended.
const LAG_DAYS = 16;
// Observed data may begin later than the range start only by this much before the
// response is flagged as partial coverage.
const COVERAGE_SLACK_DAYS = 31;

function iso(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

// Every half-month window (start date) the builder would have loaded for a range:
// start >= rangeStart and end <= today - LAG_DAYS. Pure and deterministic.
export function expectedWindows(startDateIso, todayIso) {
  const start = Date.parse(startDateIso);
  const today = Date.parse(todayIso);
  if (!Number.isFinite(start) || !Number.isFinite(today)) return [];
  const limit = today - LAG_DAYS * DAY_MS;
  const out = [];
  const first = new Date(start);
  let y = first.getUTCFullYear();
  let m = first.getUTCMonth();
  for (;;) {
    for (const [day, endY, endM, endD] of [[1, y, m, 16], [16, y + (m === 11 ? 1 : 0), (m + 1) % 12, 1]]) {
      const s = Date.UTC(y, m, day);
      const e = Date.UTC(endY, endM, endD);
      if (s >= start && e <= limit) out.push(iso(s));
    }
    if (Date.UTC(y, m, 1) > limit) break;
    m += 1;
    if (m === 12) { y += 1; m = 0; }
  }
  return out;
}

// Reads only the pre-aggregated table. Columns are written by the build script:
// lat, lng, window_start, window_end, sample_hours, temp_sum, temp_min, temp_max,
// precip_sum, humidity_sum, humidity_n, first_observed_at, last_observed_at.
// Windows with no raw rows are stored as sentinel rows (NULL lat/lng, 0 hours) so
// completeness can be measured. Windows overlapping the range start are included.
// weather_insights is a linked, read-only dataset. The aggregate must live in a
// writable dataset chosen by the owner, so there is no default table.
export const READ_ONLY_DATASETS = ['weather_insights'];
export function writableAggregateTable(value) {
  const table = String(value || '').trim();
  if (!/^[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$/.test(table)) return '';
  return READ_ONLY_DATASETS.includes(table.split('.')[1].toLowerCase()) ? '' : table;
}

export function aggregateSql(table) {
  if (typeof table !== 'string' || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$/.test(table)) {
    throw new Error('invalid_weather_insights_aggregate_table');
  }
  const tick = String.fromCharCode(96);
  const t = tick + table + tick;
  return [
    'WITH coverage AS (',
    '  SELECT MIN(window_start) AS first_window,',
    '    ARRAY_AGG(DISTINCT window_start ORDER BY window_start) AS window_starts',
    '  FROM ' + t,
    '  WHERE window_start >= @start_date',
    '),',
    'candidate AS (',
    '  SELECT lat, lng,',
    '    SQRT(POW((lat - @lat) * 111.0, 2) + POW((lng - @lng) * 111.0 * COS(RADIANS(@lat)), 2)) AS distance_km',
    '  FROM ' + t,
    '  WHERE window_end > @start_date',
    '    AND lat BETWEEN @lat - 0.3 AND @lat + 0.3',
    '    AND lng BETWEEN @lng - 0.3 AND @lng + 0.3',
    '  GROUP BY lat, lng',
    '  HAVING distance_km <= 10',
    '  ORDER BY distance_km',
    '  LIMIT 1',
    '),',
    'base AS (',
    '  SELECT a.*, c.distance_km',
    '  FROM ' + t + ' AS a JOIN candidate AS c ON a.lat = c.lat AND a.lng = c.lng',
    '  WHERE a.window_end > @start_date',
    '),',
    'monthly AS (',
    '  SELECT EXTRACT(MONTH FROM window_start) AS month,',
    '    SAFE_DIVIDE(SUM(temp_sum), SUM(sample_hours)) AS mean_temperature_c,',
    '    SUM(precip_sum) AS precipitation_mm,',
    '    SAFE_DIVIDE(SUM(humidity_sum), SUM(humidity_n)) AS mean_humidity_pct',
    '  FROM base GROUP BY month',
    ')',
    'SELECT',
    '  (SELECT first_window FROM coverage) AS first_window,',
    '  (SELECT window_starts FROM coverage) AS window_starts,',
    '  ANY_VALUE(distance_km) AS grid_distance_km,',
    '  MIN(first_observed_at) AS coverage_start,',
    '  MAX(last_observed_at) AS coverage_end,',
    '  SUM(sample_hours) AS sample_hours,',
    '  SAFE_DIVIDE(SUM(temp_sum), SUM(sample_hours)) AS mean_temperature_c,',
    '  MIN(temp_min) AS min_temperature_c,',
    '  MAX(temp_max) AS max_temperature_c,',
    '  SUM(precip_sum) AS precipitation_mm,',
    '  SAFE_DIVIDE(SUM(humidity_sum), SUM(humidity_n)) AS mean_humidity_pct,',
    '  ARRAY(SELECT AS STRUCT month, mean_temperature_c, precipitation_mm, mean_humidity_pct',
    '    FROM monthly ORDER BY month) AS monthly',
    'FROM base',
  ].join('\n');
}

function dayString(value) {
  const raw = value && typeof value === 'object' && 'value' in value ? value.value : value;
  const ms = Date.parse(String(raw || ''));
  return Number.isFinite(ms) ? iso(ms) : null;
}

// True only when every expected half-month window for the range is present in the
// aggregate (empty windows count via sentinel rows). No missing window is tolerated
// except the newest LAG_DAYS, which the builder has not loaded yet. Otherwise the
// caller must fail closed instead of labelling a partial load as 1y or 5y.
export function aggregateComplete(row, startDateIso, todayIso) {
  if (!row || !Array.isArray(row.window_starts)) return false;
  const expected = expectedWindows(startDateIso, todayIso);
  if (expected.length === 0) return false;
  const loaded = new Set(row.window_starts.map(dayString).filter(Boolean));
  return expected.every((day) => loaded.has(day));
}

// True when observed data begins noticeably after the requested range start, for
// example a raw table shorter than five years. The windows exist but hold no data.
export function coveragePartial(coverageStart, startDateIso) {
  const observed = Date.parse(String(coverageStart || ''));
  const start = Date.parse(startDateIso);
  if (!Number.isFinite(observed) || !Number.isFinite(start)) return true;
  return observed > start + COVERAGE_SLACK_DAYS * DAY_MS;
}
