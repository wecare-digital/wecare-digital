#!/usr/bin/env node
/* VayuLok free-tier safety contract: runs in the Amplify production build. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { execFileSync } = require('node:child_process');

function read(path) { return readFileSync(path, 'utf8'); }
const live = read('src/components/VayuLokLive.tsx');
const insights = read('src/components/VayuLokWeatherInsights.tsx');
const backend = read('gcp/vayulok-weather-insights/server.mjs');
const gateway = read('scripts/provision_vayulok_environment.py');

// The 2D map has a real, generously-sized viewport and its own column on
// desktop. The whole Air/Weather card follows normal page scrolling without
// clipping; phones/tablets show the full map before the complete detail card.
assert(live.includes("fitBounds?.( INDIA_OVERVIEW_BOUNDS, 24 )"), 'India overview fit is missing');
assert(live.includes('north: 37.5,') && live.includes('south: 6.0,')
  && live.includes('east: 98.0,') && live.includes('west: 67.5,'),
  'India overview bounds must include mainland and island regions');
assert(live.includes('--vl-map-height:clamp(500px,calc(100svh - 112px),820px)'),
  "desktop sticky map must fit the user's viewport height");
assert(live.includes('--vl-map-height:clamp(460px,77vw,720px)'),
  'tablet map viewport must not be artificially cropped');
assert(live.includes('--vl-map-height:clamp(440px,112vw,640px)'),
  'phone map viewport must show the whole India overview');
assert(live.includes('grid-template-columns:minmax(0,1fr) minmax(320px,416px)'),
  'desktop map must have an unobstructed column alongside the detail card');
assert(live.includes('grid-template-rows:var(--vl-map-height) auto'),
  'narrow map must have a separate real grid track before the detail card');
assert(live.includes('.vl-live-map-canvas,.vl-live-map-placeholder{position:sticky;top:80px;grid-area:1/1;align-self:start;width:100%;height:var(--vl-map-height)'),
  'desktop map and placeholder must share a full-size sticky viewport');
assert(live.includes('.vl-live-weather-visual{position:sticky;top:80px;grid-area:1/1;align-self:start;height:var(--vl-map-height)') &&
  live.includes('clip-path:inset(0 0 48px 0 round var(--panel-r))'),
  'weather visual must align with the map and leave attribution visible');
assert(live.includes('.vl-live-air-card-wrap{position:relative;z-index:12;grid-area:1/2;'),
  'full Air/Weather card must be a separate desktop grid column');
assert(!live.includes('max-height:calc(100% - 32px)') &&
  !live.includes('overflow-y:auto;overscroll-behavior-y:contain;scrollbar-gutter:stable'),
  'Air/Weather card must use page scrolling, not an inner clipped scroll area');
assert(!live.includes('padding-top:clamp(300px,50vw,440px)')
  && !live.includes('padding-top:clamp(300px,75vw,360px)')
  && !live.includes('max-height:740px'),
  'old map crop/padding-height code must be gone');
assert(live.lastIndexOf('.vl-live-mobile-snapshot{display:none}') >
  live.lastIndexOf('display:block;position:absolute;z-index:13;'), 'mobile summary must not cover India');

// Cost protection: public AWS gateway throttle stays narrow on future provisioning.
assert(gateway.includes('RATE_LIMIT = 2.0') && gateway.includes('BURST_LIMIT = 4'),
  'VayuLok AWS route throttling must preserve the audited 2 rps / 4 burst cap');
// Paid AQI heatmap tiles should require an explicit user action.
assert(live.includes("const [ layer, setLayer ] = useState<'AQI' | 'PM25' | null>( null );"),
  'paid heatmap tiles must be off on first load');
assert(live.includes('mapViewRequested'), 'paid Maps loading must be deferred');
assert(live.includes('const SEARCH_DEBOUNCE_MS = 300;'), 'autocomplete debounce missing');

// Keep history automatic, preserve Google's map attribution and avoid hiding it.
assert(live.includes('<VayuLokWeatherInsights\n                          lat={ place.lat }'),
  'weather history must continue to mount automatically');
assert(!live.includes('.vl-live :global(.gm-style-cc),') &&
  !live.includes('.vl-live :global(img[alt="Google"])') &&
  !live.includes('.vl-live :global(a[aria-label="Google Maps"])'),
  'Google Maps attribution must remain visible');
assert(insights.includes('void run();'), 'automatic long-term history fetch missing');
assert(insights.includes('localStorage.setItem( LOCAL_HISTORY_STORE'),
  'persistent browser history cache missing');
assert(insights.includes('HISTORY_CACHE_TTL_MS = 24 * 60 * 60 * 1000'),
  'history cache must have a bounded freshness window');
assert(insights.includes('query_cost_cap_exceeded'),
  'quota failure must have an honest unavailable state');
assert(insights.includes("fetch( `${INSIGHTS_URL}/v1/weather-insights/status`") &&
  !insights.includes("if ( range !== '30d' )"),
  'all uncached history ranges must verify a live 1 GiB server guard before BigQuery');

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
