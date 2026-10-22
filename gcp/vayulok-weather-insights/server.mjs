import http from 'node:http';
import { URL } from 'node:url';

const PORT = Number(process.env.PORT || 8080);
const PROJECT = process.env.GOOGLE_CLOUD_PROJECT || process.env.BQ_PROJECT || 'wecaredigitalbw';
const DATASET = process.env.WEATHER_INSIGHTS_DATASET || 'weather_insights';
const LOCATION = process.env.BQ_LOCATION || 'US';
const TABLE_OVERRIDE = process.env.WEATHER_INSIGHTS_TABLE || '';
const MAX_BYTES_BILLED = String(process.env.BQ_MAX_BYTES_BILLED || '134217728');
const CACHE_TTL_MS = Number(process.env.INSIGHTS_CACHE_TTL_MS || 6 * 60 * 60 * 1000);
const RATE_LIMIT_PER_MINUTE = Number(process.env.INSIGHTS_RATE_LIMIT_PER_MINUTE || 30);
const ALLOW_ORIGINLESS = process.env.ALLOW_ORIGINLESS === '1';
const DEBUG_SCHEMA = process.env.DEBUG_SCHEMA === '1';
const ALLOWED_ORIGINS = new Set(
  (process.env.ALLOWED_ORIGINS || 'https://wecare.digital,https://www.wecare.digital')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean),
);

const cache = new Map();
const rate = new Map();
let tokenCache = { token: '', expiresAt: 0 };

const COLUMN_CANDIDATES = {
  time: ['observed_at', 'observation_time', 'timestamp', 'valid_time', 'date_time', 'datetime'],
  lat: ['latitude', 'lat', 'grid_latitude'],
  lng: ['longitude', 'lng', 'lon', 'grid_longitude'],
  temp: ['temperature_c', 'temperature_celsius', 'air_temperature_c', 'temp_c'],
  rain: ['precipitation_mm', 'rain_mm', 'qpf_mm'],
  humidity: ['relative_humidity_pct', 'humidity_pct'],
};

function json(res, status, body, origin = '') {
  const headers = {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': status === 200 ? 'public, max-age=300, stale-while-revalidate=3600' : 'no-store',
    'x-content-type-options': 'nosniff',
  };
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    headers['access-control-allow-origin'] = origin;
    headers.vary = 'Origin';
  }
  res.writeHead(status, headers);
  res.end(JSON.stringify(body));
}

function corsAllowed(req) {
  const origin = String(req.headers.origin || '');
  if (!origin) return ALLOW_ORIGINLESS;
  return ALLOWED_ORIGINS.has(origin);
}

function rateAllowed(req) {
  const forwarded = String(req.headers['x-forwarded-for'] || '');
  const key = forwarded.split(',')[0].trim() || req.socket.remoteAddress || 'unknown';
  const minute = Math.floor(Date.now() / 60000);
  const current = rate.get(key);
  if (!current || current.minute !== minute) {
    rate.set(key, { minute, count: 1 });
    return true;
  }
  current.count += 1;
  return current.count <= RATE_LIMIT_PER_MINUTE;
}

function parseNumber(value, min, max) {
  const n = Number(value);
  return Number.isFinite(n) && n >= min && n <= max ? n : null;
}

function startDate(range) {
  const now = new Date();
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  if (range === '30d') d.setUTCDate(d.getUTCDate() - 30);
  else if (range === '1y') d.setUTCFullYear(d.getUTCFullYear() - 1);
  else d.setUTCFullYear(d.getUTCFullYear() - 5);
  return d.toISOString().slice(0, 10);
}

function validPath(value) {
  return /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(value);
}

function validTable(value) {
  return /^[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$/.test(value);
}

async function accessToken() {
  if (tokenCache.token && Date.now() < tokenCache.expiresAt - 60000) return tokenCache.token;
  const response = await fetch(
    'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
    { headers: { 'Metadata-Flavor': 'Google' } },
  );
  if (!response.ok) throw new Error('metadata_token_' + response.status);
  const body = await response.json();
  tokenCache = {
    token: body.access_token,
    expiresAt: Date.now() + Number(body.expires_in || 300) * 1000,
  };
  return tokenCache.token;
}

async function bqFetch(path, init = {}) {
  const token = await accessToken();
  const response = await fetch('https://bigquery.googleapis.com/bigquery/v2/' + path, {
    ...init,
    headers: {
      authorization: 'Bearer ' + token,
      'content-type': 'application/json',
      ...(init.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = body?.error?.message || 'bigquery_http_' + response.status;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return body;
}

function flattenFields(fields, prefix = '') {
  const out = [];
  for (const field of fields || []) {
    const path = prefix ? prefix + '.' + field.name : field.name;
    out.push({ path, type: field.type, mode: field.mode || 'NULLABLE' });
    if (Array.isArray(field.fields)) out.push(...flattenFields(field.fields, path));
  }
  return out;
}

function envColumn(name) {
  const value = String(process.env[name] || '').trim();
  if (!value) return '';
  if (!validPath(value)) throw new Error('invalid_column_' + name.toLowerCase());
  return value;
}

function findCandidate(fields, candidates) {
  for (const candidate of candidates) {
    const match = fields.find((field) => field.path.toLowerCase() === candidate);
    if (match) return match.path;
  }
  return '';
}

async function discoverSource() {
  let table = TABLE_OVERRIDE.trim();
  if (table && !validTable(table)) throw new Error('invalid_weather_insights_table');

  if (!table) {
    const listing = await bqFetch(
      'projects/' + encodeURIComponent(PROJECT) +
      '/datasets/' + encodeURIComponent(DATASET) +
      '/tables?maxResults=100',
    );
    const tables = (listing.tables || [])
      .map((entry) => entry.tableReference)
      .filter(Boolean);
    if (tables.length !== 1) {
      return {
        ready: false,
        reason: tables.length ? 'table_configuration_required' : 'linked_dataset_empty',
        tableCount: tables.length,
        tables: DEBUG_SCHEMA ? tables.map((t) => t.tableId) : undefined,
      };
    }
    table = tables[0].projectId + '.' + tables[0].datasetId + '.' + tables[0].tableId;
  }

  const parts = table.split('.');
  const metadata = await bqFetch(
    'projects/' + encodeURIComponent(parts[0]) +
    '/datasets/' + encodeURIComponent(parts[1]) +
    '/tables/' + encodeURIComponent(parts[2]),
  );
  const fields = flattenFields(metadata.schema?.fields || []);

  const columns = {
    time: envColumn('WEATHER_INSIGHTS_TIME_COLUMN') || findCandidate(fields, COLUMN_CANDIDATES.time),
    lat: envColumn('WEATHER_INSIGHTS_LAT_COLUMN') || findCandidate(fields, COLUMN_CANDIDATES.lat),
    lng: envColumn('WEATHER_INSIGHTS_LNG_COLUMN') || findCandidate(fields, COLUMN_CANDIDATES.lng),
    temp: envColumn('WEATHER_INSIGHTS_TEMP_C_COLUMN') || findCandidate(fields, COLUMN_CANDIDATES.temp),
    rain: envColumn('WEATHER_INSIGHTS_RAIN_MM_COLUMN') || findCandidate(fields, COLUMN_CANDIDATES.rain),
    humidity: envColumn('WEATHER_INSIGHTS_HUMIDITY_PCT_COLUMN') || findCandidate(fields, COLUMN_CANDIDATES.humidity),
  };

  const missing = ['time', 'lat', 'lng', 'temp'].filter((key) => !columns[key]);
  return {
    ready: missing.length === 0,
    reason: missing.length ? 'column_configuration_required' : 'ready',
    table,
    columns,
    missing,
    schema: DEBUG_SCHEMA ? fields : undefined,
  };
}

function param(name, type, value) {
  return {
    name,
    parameterType: { type },
    parameterValue: { value: String(value) },
  };
}

function decodeValue(field, cell) {
  if (!cell || cell.v === null || cell.v === undefined) return null;
  if (field.type === 'RECORD' || field.type === 'STRUCT') {
    const nested = {};
    const values = cell.v?.f || [];
    (field.fields || []).forEach((child, index) => {
      nested[child.name] = decodeValue(child, values[index]);
    });
    return nested;
  }
  if (field.mode === 'REPEATED') {
    return (cell.v || []).map((item) => decodeValue({ ...field, mode: 'NULLABLE' }, item));
  }
  const value = cell.v;
  if (['INTEGER', 'INT64', 'FLOAT', 'FLOAT64', 'NUMERIC', 'BIGNUMERIC'].includes(field.type)) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  if (field.type === 'BOOLEAN' || field.type === 'BOOL') return value === true || value === 'true';
  return value;
}

function decodeRows(result) {
  const fields = result.schema?.fields || [];
  return (result.rows || []).map((row) => {
    const out = {};
    fields.forEach((field, index) => {
      out[field.name] = decodeValue(field, row.f?.[index]);
    });
    return out;
  });
}

async function runQuery(query, parameters) {
  const request = {
    query,
    useLegacySql: false,
    useQueryCache: true,
    maximumBytesBilled: MAX_BYTES_BILLED,
    timeoutMs: 20000,
    location: LOCATION,
    parameterMode: 'NAMED',
    queryParameters: parameters,
  };
  let result = await bqFetch(
    'projects/' + encodeURIComponent(PROJECT) + '/queries',
    { method: 'POST', body: JSON.stringify(request) },
  );

  if (!result.jobComplete && result.jobReference?.jobId) {
    const jobId = encodeURIComponent(result.jobReference.jobId);
    for (let attempt = 0; attempt < 8 && !result.jobComplete; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 350));
      result = await bqFetch(
        'projects/' + encodeURIComponent(PROJECT) +
        '/queries/' + jobId +
        '?location=' + encodeURIComponent(result.jobReference.location || LOCATION) +
        '&timeoutMs=10000',
      );
    }
  }
  if (!result.jobComplete) throw new Error('bigquery_query_timeout');
  return decodeRows(result);
}

function weatherSql(source) {
  const tick = String.fromCharCode(96);
  const table = tick + source.table + tick;
  const c = source.columns;
  const rain = c.rain ? 'SAFE_CAST(' + c.rain + ' AS FLOAT64)' : 'CAST(NULL AS FLOAT64)';
  const humidity = c.humidity ? 'SAFE_CAST(' + c.humidity + ' AS FLOAT64)' : 'CAST(NULL AS FLOAT64)';

  return [
    'WITH candidate_grid AS (',
    '  SELECT',
    '    SAFE_CAST(' + c.lat + ' AS FLOAT64) AS grid_lat,',
    '    SAFE_CAST(' + c.lng + ' AS FLOAT64) AS grid_lng,',
    '    POW(SAFE_CAST(' + c.lat + ' AS FLOAT64) - @lat, 2) +',
    '      POW((SAFE_CAST(' + c.lng + ' AS FLOAT64) - @lng) * COS(RADIANS(@lat)), 2) AS distance_score',
    '  FROM ' + table,
    '  WHERE DATE(' + c.time + ') >= @start_date',
    '    AND SAFE_CAST(' + c.lat + ' AS FLOAT64) BETWEEN @lat - 0.3 AND @lat + 0.3',
    '    AND SAFE_CAST(' + c.lng + ' AS FLOAT64) BETWEEN @lng - 0.3 AND @lng + 0.3',
    '  GROUP BY grid_lat, grid_lng',
    '  ORDER BY distance_score',
    '  LIMIT 1',
    '),',
    'base AS (',
    '  SELECT',
    '    ' + c.time + ' AS observed_at,',
    '    SAFE_CAST(' + c.temp + ' AS FLOAT64) AS temperature_c,',
    '    ' + rain + ' AS precipitation_mm,',
    '    ' + humidity + ' AS humidity_pct',
    '  FROM ' + table + ', candidate_grid',
    '  WHERE DATE(' + c.time + ') >= @start_date',
    '    AND SAFE_CAST(' + c.lat + ' AS FLOAT64) = grid_lat',
    '    AND SAFE_CAST(' + c.lng + ' AS FLOAT64) = grid_lng',
    '),',
    'monthly AS (',
    '  SELECT',
    '    EXTRACT(MONTH FROM observed_at) AS month,',
    '    AVG(temperature_c) AS mean_temperature_c,',
    '    SUM(precipitation_mm) AS precipitation_mm,',
    '    AVG(humidity_pct) AS mean_humidity_pct',
    '  FROM base',
    '  GROUP BY month',
    ')',
    'SELECT',
    '  (SELECT grid_lat FROM candidate_grid) AS grid_lat,',
    '  (SELECT grid_lng FROM candidate_grid) AS grid_lng,',
    '  SQRT(',
    '    POW(((SELECT grid_lat FROM candidate_grid) - @lat) * 111.0, 2) +',
    '    POW(((SELECT grid_lng FROM candidate_grid) - @lng) * 111.0 * COS(RADIANS(@lat)), 2)',
    '  ) AS grid_distance_km,',
    '  MIN(observed_at) AS coverage_start,',
    '  MAX(observed_at) AS coverage_end,',
    '  COUNT(*) AS sample_hours,',
    '  AVG(temperature_c) AS mean_temperature_c,',
    '  MIN(temperature_c) AS min_temperature_c,',
    '  MAX(temperature_c) AS max_temperature_c,',
    '  SUM(precipitation_mm) AS precipitation_mm,',
    '  AVG(humidity_pct) AS mean_humidity_pct,',
    '  ARRAY(',
    '    SELECT AS STRUCT month, mean_temperature_c, precipitation_mm, mean_humidity_pct',
    '    FROM monthly ORDER BY month',
    '  ) AS monthly',
    'FROM base',
  ].join('\n');
}

function cleanSummary(row, range) {
  if (!row || !Number(row.sample_hours)) return null;
  const round = (value, digits = 1) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return null;
    const scale = 10 ** digits;
    return Math.round(n * scale) / scale;
  };
  return {
    range,
    gridDistanceKm: round(row.grid_distance_km, 2),
    sampleHours: Number(row.sample_hours),
    meanTemperatureC: round(row.mean_temperature_c),
    minTemperatureC: round(row.min_temperature_c),
    maxTemperatureC: round(row.max_temperature_c),
    precipitationMm: round(row.precipitation_mm),
    meanHumidityPct: round(row.mean_humidity_pct),
    monthly: Array.isArray(row.monthly) ? row.monthly.map((item) => ({
      month: Number(item.month),
      meanTemperatureC: round(item.mean_temperature_c),
      precipitationMm: round(item.precipitation_mm),
      meanHumidityPct: round(item.mean_humidity_pct),
    })) : [],
    source: 'Google Weather Insights via BigQuery',
  };
}

async function statusPayload() {
  try {
    const source = await discoverSource();
    return {
      ok: source.ready,
      project: PROJECT,
      dataset: DATASET,
      location: LOCATION,
      reason: source.reason,
      tableCount: source.tableCount,
      table: source.ready || DEBUG_SCHEMA ? source.table : undefined,
      columns: source.ready || DEBUG_SCHEMA ? source.columns : undefined,
      missing: source.missing,
      tables: source.tables,
      schema: source.schema,
    };
  } catch (error) {
    const message = String(error?.message || error);
    if (/Not found|404|dataset/i.test(message)) {
      return { ok: false, project: PROJECT, dataset: DATASET, location: LOCATION, reason: 'linked_dataset_missing' };
    }
    return { ok: false, project: PROJECT, dataset: DATASET, location: LOCATION, reason: 'bigquery_unavailable', detail: DEBUG_SCHEMA ? message : undefined };
  }
}

async function handleInsights(req, res, url) {
  const origin = String(req.headers.origin || '');
  if (!corsAllowed(req)) return json(res, 403, { error: 'origin_not_allowed' }, origin);
  if (!rateAllowed(req)) return json(res, 429, { error: 'rate_limited' }, origin);

  const lat = parseNumber(url.searchParams.get('lat'), -90, 90);
  const lng = parseNumber(url.searchParams.get('lng'), -180, 180);
  const range = String(url.searchParams.get('range') || '5y').toLowerCase();
  if (lat === null || lng === null || !['30d', '1y', '5y'].includes(range)) {
    return json(res, 400, { error: 'invalid_request' }, origin);
  }

  const cacheKey = [Math.round(lat * 10) / 10, Math.round(lng * 10) / 10, range].join(':');
  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.ts < CACHE_TTL_MS) {
    return json(res, 200, { ...cached.body, cached: true }, origin);
  }

  let source;
  try {
    source = await discoverSource();
  } catch (error) {
    return json(res, 503, { error: 'weather_insights_unavailable' }, origin);
  }
  if (!source.ready) {
    return json(res, 503, { error: source.reason, missing: source.missing || [] }, origin);
  }

  try {
    const rows = await runQuery(weatherSql(source), [
      param('lat', 'FLOAT64', lat),
      param('lng', 'FLOAT64', lng),
      param('start_date', 'DATE', startDate(range)),
    ]);
    const summary = cleanSummary(rows[0], range);
    if (!summary) return json(res, 404, { error: 'no_historical_weather_for_location' }, origin);
    const body = { ok: true, ...summary };
    cache.set(cacheKey, { ts: Date.now(), body });
    return json(res, 200, body, origin);
  } catch (error) {
    const message = String(error?.message || error);
    const tooLarge = /maximum bytes billed|bytes.*limit|billingTierLimitExceeded/i.test(message);
    return json(res, tooLarge ? 422 : 503, {
      error: tooLarge ? 'query_cost_cap_exceeded' : 'weather_insights_query_failed',
      detail: DEBUG_SCHEMA ? message : undefined,
    }, origin);
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', 'http://localhost');

  if (req.method === 'OPTIONS') {
    const origin = String(req.headers.origin || '');
    if (!origin || !ALLOWED_ORIGINS.has(origin)) return json(res, 403, { error: 'origin_not_allowed' }, origin);
    res.writeHead(204, {
      'access-control-allow-origin': origin,
      'access-control-allow-methods': 'GET,OPTIONS',
      'access-control-allow-headers': 'content-type',
      'access-control-max-age': '3600',
      vary: 'Origin',
    });
    return res.end();
  }

  if (req.method === 'GET' && url.pathname === '/healthz') {
    return json(res, 200, { ok: true, service: 'vayulok-weather-insights' });
  }

  if (req.method === 'GET' && url.pathname === '/v1/weather-insights/status') {
    const status = await statusPayload();
    return json(res, status.ok ? 200 : 503, status);
  }

  if (req.method === 'GET' && url.pathname === '/v1/weather-insights') {
    return handleInsights(req, res, url);
  }

  return json(res, 404, { error: 'not_found' });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(JSON.stringify({
    service: 'vayulok-weather-insights',
    port: PORT,
    project: PROJECT,
    dataset: DATASET,
    location: LOCATION,
    maxBytesBilled: MAX_BYTES_BILLED,
  }));
});
