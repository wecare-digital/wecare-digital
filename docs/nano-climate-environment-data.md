# Nano Climate environmental sources — integration-first

Keep the existing WECARE.DIGITAL hero, eyebrow, globe, typography, section borders,
search, map geometry, Air/Weather tabs and shared UI components. The addition is
only an extra section using the existing detail styles. No new primary navigation.

## Implemented adapters (not activated by this change)

| Provider | Contract | Hard shared upstream attempts (UTC day / month) |
|---|---|---|
| Google Elevation | Single selected coordinate, meters/resolution, no result cache | 100 / 3,100 |
| CPCB via data.gov.in | One bounded national snapshot, nearest reporting station within 25 km, per-pollutant timestamp and average; no invented units or AQI | 24 / 744 |
| EC JRC PVGIS 5.3 | Regional 3 kWp, 14% loss, optimized tilt, actual annual generation/irradiation, optional complete monthly profile | 250 / 7,750 |
| Google Solar Building Insights | Precise viewport only, nearest building DC estimate; no Data Layers, GeoTIFF, detected arrays or experimental API | 250 / 7,750 |
| SPARTAN | Verified Delhi/Jaipur filter-based files and Kanpur daily estimated PM2.5, within 50 km, historical dates and sample hours | 12 / 372 |

Every upstream attempt first reserves two conditional DynamoDB updates in one
transaction on the existing RateLimit table (id string key, isolated
nano-climate:environment: prefix). Configuration absent, quota reached, IAM
denial, transaction conflict or store failure => no upstream request. No refunds
on failures. The live table has TTL disabled; the counter does not depend on TTL.
Only open-data snapshots/results are cached; no Google Elevation/Solar content
persisted. Existing 2 rps / 4 burst public route throttle is unchanged.

## Provider credentials, activation and tests

- Existing deployed function: wecare-vayulok-environment, us-east-1, live alias.
- Backend and frontend are separate releases. New operation is location_context,
  on the existing POST /vayulok/environment route. Existing origin checks stay
  unchanged: only wecare.digital and its subdomains; do not bypass them for an
  Amplify preview hostname or add an arbitrary proxy.
- All new sources default disabled. No provider credentials, permissions, quotas,
  table configuration or live alias are modified by committing this code.
- Existing canonical server Google key currently lacks Elevation/Solar targets in
  the repository allowlist. Verify the current GCP project targets and eligible
  SKU usage, enable the approved least-privilege targets via the existing
  administrator workflow. Do not expose or rotate keys unnecessarily. Solar
  only uses buildingInsights:findClosest; other authorized callers are not
  covered by this application's counters. Published India Building Insights
  allowance is 70,000 for eligible accounts; the smaller app limits do not
  guarantee zero aggregate billing.
- CPCB needs the registered data.gov.in API key in the approved Secrets Manager
  entry wecare/nano-climate/cpcb (JSON field api_key). The existing secret inventory
  contained no CPCB credential. Verify the live API and full snapshot schema first.
  No demo/shared key. No new key obtained or copied into chat.
- PVGIS requires server-side GET (AJAX is prohibited). SPARTAN uses public
  verified CSV object keys and credits the network. Both need no new provider key.
- Run the existing Node 24 typecheck/lint/test/build plus
  python -m pytest tests/python/test_nano_climate_extended_sources.py -q.
- After required review, stage the code with the existing targeted Lambda deploy
  route: python scripts/deploy_all_lambdas.py wecare-vayulok-environment --dry-run
  then the owning release workflow with --no-publish. Use the configuration script
  dry run for the approved subset:
  python scripts/configure_nano_climate_sources.py --sources pvgis spartan
  Only authorized operators apply with --apply; Google sources additionally
  require --confirm-google-key-and-billing after checking actual key and billing.
  The script preserves existing environment variables, modifies the existing
  execution role with namespaced rights and configures $LATEST only. Validate
  before moving the live alias through the established workflow.
- Frontend build switch NEXT_PUBLIC_VAYULOK_EXTENDED=true only after the gateway
  is deployed and approved. Existing public browser-key and viewport defer gates
  remain. Selection changes cancel the previous request; no polling, no
  automatic retry and no historical map animation.

## Remaining source-specific work

Google historical-weather service is already wired with 1 GiB query cap and
10 GiB/day project quota; verify current deployed status and coverage before
additional queries. WeatherNext 3 statistics Zarr needs verified access,
real-time licensing and a bounded byte/chunk read plan; never scan expensive raw
BigQuery views. Sentinel-5P needs a verified permitted L2/derived product,
processing workflow, coverage and quality flags; catalog metadata alone is not
an atmospheric concentration. No OAQ, Aurassure, Pollen, paid Sentinel Hub,
Solar Data Layers or unverified IMD feed.

## Official sources

https://developers.google.com/maps/documentation/elevation/requests-elevation
https://www.data.gov.in/resource/real-time-air-quality-index-various-locations
https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5/api-non-interactive-service_en
https://developers.google.com/maps/documentation/solar/reference/rest/v1/buildingInsights/findClosest
https://developers.google.com/maps/billing-and-pricing/pricing-india
https://registry.opendata.aws/spartan-cloud/
https://www.spartan-network.org/data
https://developers.google.com/weathernext/guides/access-forecast
https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel5P.html
