# Nano Climate Atlas development preview

Application-first layout, on the existing Nano Climate route. Existing Google Maps, Air Quality, Weather, alerts, forecasts, recent history, historical weather, health profiles, search and optional place tools are reused. The legacy approved hero/globe remains available on the default build.

## Preview

Use Node 24+ and npm 11.6.2 with the normal authorized development configuration.

```bash
npm ci
NEXT_PUBLIC_NANO_CLIMATE_ATLAS=true npm run dev
```

Open http://localhost:3000/atmos/nano-climate/. The build-time switch defaults to false. Without the existing authorized browser key, maps and readings show unavailable states. Never copy production secrets into local preview; preserve referrer restrictions.

Run npm run typecheck, npm run lint, npm test and npm run build with the required toolchain before release.

## Scope

- Compact page heading, map-first workspace, Air/Weather/AQI/PM2.5 layer selector and collapsible place tools.
- Conditions / Forecast / History, with actual returned point-data timeline and existing inspection indices. Current map layers are not a time animation.
- Existing automatic history retrieval is preserved, including the historical-weather query guard. The History view changes presentation, not billing or request activation.
- Location changes clear old Atlas readings before displaying the new place.
- Existing provider guards, caches, feature flags and map attribution remain. Heatmaps still require an explicit selection. No new provider endpoints, dependencies, credentials or quota changes.

## Remaining development

CPCB, PVGIS, Solar Building Insights, independent WeatherNext 3 statistics, SPARTAN, Sentinel-5P and terrain/elevation remain to be integrated. Do not advertise unwired feeds or substitute mock data. Solar needs persistent atomic daily/monthly pre-request limits and an endpoint allowlist excluding Data Layers and GeoTIFF. WeatherNext 3 must not scan the expensive raw BigQuery views. Verify billing-account SKU consumption and keep the 10 GiB/day project and per-query BigQuery limits. OAQ, Aurassure and paid Sentinel Hub processing are excluded.

Verify the real rendered layout and live-provider behavior in an authorized preview, accessibility and required CI before enabling Atlas in production. This branch does not deploy or change billing.
