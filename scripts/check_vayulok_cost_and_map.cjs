#!/usr/bin/env node
/* VayuLok free-tier safety contract: runs in the Amplify production build. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { execFileSync } = require('node:child_process');

function read(path) { return readFileSync(path, 'utf8'); }
const live = read('src/components/VayuLokLive.tsx');
const insights = read('src/components/VayuLokWeatherInsights.tsx');
const backend = read('gcp/vayulok-weather-insights/server.mjs');

// The real 2D map must be bounded. Don't mistake the standalone globe for it.
assert(live.includes("fitBounds?.( INDIA_OVERVIEW_BOUNDS, 24 )"), 'India overview fit is missing');
assert(live.includes('height:clamp(500px,72svh,740px)'), 'desktop 2D map height is unbounded');
assert(live.includes('@media(max-width:1050px)'), 'narrow tablet/mobile layout is missing');
assert(live.includes('padding-top:clamp(300px,50vw,440px)'), 'tablet map does not reserve compact height');
assert(live.includes('padding-top:clamp(300px,75vw,360px)'), 'phone map does not reserve compact height');
assert(live.lastIndexOf('.vl-live-mobile-snapshot{display:none}') >
  live.lastIndexOf('display:block;position:absolute;z-index:13;'), 'mobile summary must not cover India');

// Cost protection: paid AQI heatmap tiles should require an explicit user action.
assert(live.includes("const [ layer, setLayer ] = useState<'AQI' | 'PM25' | null>( null );"),
  'paid heatmap tiles must be off on first load');
assert(live.includes('mapViewRequested'), 'paid Maps loading must be deferred');
assert(live.includes('const SEARCH_DEBOUNCE_MS = 300;'), 'autocomplete debounce missing');

// Do not regress user-selected automatic history or attribution presentation.
assert(live.includes('<VayuLokWeatherInsights\n                          lat={ place.lat }'),
  'weather history must continue to mount automatically');
assert(live.includes('.vl-live :global(.gm-style-cc),'),
  'existing attribution display was changed unexpectedly');
assert(insights.includes('void run();'), 'automatic long-term history fetch missing');
assert(insights.includes('localStorage.setItem( LOCAL_HISTORY_STORE'),
  'persistent browser history cache missing');
assert(insights.includes('HISTORY_CACHE_TTL_MS = 24 * 60 * 60 * 1000'),
  'history cache must have a bounded freshness window');
assert(insights.includes('query_cost_cap_exceeded'),
  'quota failure must have an honest unavailable state');
assert(insights.includes("fetch( `${INSIGHTS_URL}/v1/weather-insights/status`"),
  '1Y/5Y must verify a live server query guard before allowing expensive requests');

// Cloud Run has a hard 1GiB query cap and a bounded instance-level daily
// attempt budget. Project-wide Cloud quotas still must be configured in GCP.
assert(backend.includes('HARD_MAX_BYTES_PER_QUERY = 1073741824n'),
  'BigQuery per-query safety limit missing');
assert(backend.includes('reserveQueryBudget()'), 'daily query guard missing');
assert(backend.includes('inFlight.get(cacheKey)'), 'in-flight query coalescing missing');
assert(backend.includes("param('lat', 'FLOAT64', gridLat)"),
  'BigQuery query parameters must align with the 0.1-degree cache grid');

execFileSync(process.execPath, ['--check', 'gcp/vayulok-weather-insights/server.mjs'], {
  stdio: 'inherit',
});
console.log('VayuLok cost and India 2D map contract: PASS');
