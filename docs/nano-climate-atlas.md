# Nano Climate development preview

The alternate Atlas layout has been withdrawn from this review branch. Preserve the current WECARE.DIGITAL design exactly: shared RotatingHero and BrandBadge (eyebrow), rotating capability pill and colour pairs, approved globe, breadcrumbs, original map/grid dimensions, search styling, Air/Weather controls, lime heading accents, hairline section borders, full panels, and place tools. Use the existing site-wide components and tokens. No new visual treatment or navigation is enabled in this revision.

The existing Air Quality, Weather, forecasts, history, alerts, heatmaps, location search and utilities remain functional, with the existing provider guards, source attribution and cache policies. The development flag now enables the location-reading reset safeguard only; it does not replace the hero or alter layout. Prior Atlas design work remains in Git history but is not used for this preview.

## Preview

Use the repository's Node 24+ and npm 11.6.2 configuration. Run:

```bash
npm ci
NEXT_PUBLIC_NANO_CLIMATE_ATLAS=true npm run dev
```

Open http://localhost:3000/atmos/nano-climate/. Use the existing authorized browser API key restrictions; without an authorized key the app shows unavailable states. Do not copy production secrets into local preview or broaden key restrictions. Run the existing typecheck, lint, tests and full build before release.

## Remaining development

CPCB, PVGIS, guarded Solar Building Insights, independent WeatherNext 3 statistics, SPARTAN, Sentinel-5P and terrain/elevation remain separate integration work. New data must use the existing component system, without removing existing aesthetics. Solar needs persistent atomic pre-request daily/monthly limits and exclusion of Data Layers/GeoTIFF. Preserve the BigQuery query and project limits; no OAQ, Aurassure or paid Sentinel Hub processing. Verify account-wide SKU usage.

The rejected alternate layout is not approved for production. This correction is limited to the existing development preview branch.
