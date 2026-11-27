// Pure helpers for the pre-aggregated 1y/5y historical weather summary. Kept apart
// from server.mjs so the SQL shape and completeness rules can be tested directly.

const DAY_MS = 86400000;
// A half-month window is 15 to 16 days. Requiring one window per 16 days of the
// range tolerates a few skipped windows but not a partially loaded table.
const WINDOW_DAYS = 16;

// Reads only the pre-aggregated table. Columns are written by the build script:
// lat, lng, window_start, window_end, sample_hours, temp_sum, temp_min, temp_max,
// precip_sum, humidity_sum, humidity_n, first_observed_at, last_observed_at.
// Windows with no raw rows are stored as sentinel rows (NULL lat/lng, 0 hours) so
// completeness can be measured. Windows overlapping the range start are included.
export function aggregateSql(table) {
  if (typeof table !== 'string' || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$/.test(table)) {
    throw new Error('invalid_weather_insights_aggregate_table');
  }
  const tick = String.fromCharCode(96);
  const t = tick + table + tick;
  return [
    'WITH coverage AS (',
    '  SELECT MIN(window_start) AS first_window, COUNT(DISTINCT window_start) AS windows_loaded',
    '  FROM ' + t,
    '  WHERE window_end > @start_date',
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
    '  (SELECT windows_loaded FROM coverage) AS windows_loaded,',
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

function dateValue(value) {
  const raw = value && typeof value === 'object' && 'value' in value ? value.value : value;
  const ms = Date.parse(String(raw || ''));
  return Number.isFinite(ms) ? ms : null;
}

// True only when the aggregate covers the requested range: it reaches back to the
// range start and holds roughly one window per half month. Otherwise the caller
// must fail closed instead of labelling a partial load as 1y or 5y.
export function aggregateComplete(row, startDateIso, todayIso) {
  if (!row) return false;
  const first = dateValue(row.first_window);
  const start = dateValue(startDateIso);
  const today = dateValue(todayIso);
  const loaded = Number(row.windows_loaded);
  if (first === null || start === null || today === null || !Number.isFinite(loaded)) return false;
  const needed = Math.floor((today - start) / DAY_MS / WINDOW_DAYS);
  return first <= start + WINDOW_DAYS * DAY_MS && loaded >= needed;
}
