# Nano Climate environmental sources — integration-first

Keep the existing WECARE.DIGITAL hero, eyebrow, globe, typography, section borders,
search, map geometry, Air/Weather tabs and shared UI components. The addition is
only an extra section using the existing detail styles. No new primary navigation.

## Implemented adapters (activation status is in Verified status below)

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

## Verified status (audit 2026-11-27, production branch 62b1c01a2)

Live page: https://wecare.digital/atmos/nano-climate/ (/vayulok/ is a 404).
Lambda live alias: version 8. Amplify production build: #799. Deployed handler.py
hash equals the repository file. Status uses the definition of completion: code
tested, CI, deployed, provider authorization verified, safeguards operational,
real data retrieved, frontend shows attributed readings, browser verified,
graceful degradation.

| Integration | Status |
|---|---|
| PVGIS | Complete. Live Delhi response and card verified in a browser. Also re-verified for a second selected place (cards update with the selection). |
| SPARTAN | Complete. Live Delhi site card verified, labelled historical. |
| Google Elevation | Code, CI, deployment and budget guard done. Not activated (not in VAYULOK_EXTENDED_SOURCES). Server key API restriction, Elevation API enablement and billing not verified (no Google Cloud credentials were available). |
| Google Solar Building Insights | Same as Elevation. Also only runs for a precise building viewport. |
| CPCB | Code and deployment done. Blocked: secret wecare/nano-climate/cpcb does not exist and needs a registered data.gov.in key from the owner. scripts/configure_nano_climate_sources.py already adds the read statement and VAYULOK_CPCB_SECRET once the secret exists. |
| Historical Weather | 30d (0.987 GiB dry run) reads the raw table. 1y and 5y now read a pre-aggregated table built by scripts/build_weather_history_aggregate.sh. Until that table is built and verified, 1y and 5y report the honest cost-cap state. See below. |
| WeatherNext 3 | No integration code. Statistics bucket is not anonymously readable (HTTP 401/403 verified), so access needs the Google account allowlisted through the WeatherNext data request form. Terms and chunk sizes are unverified. See below. |
| Sentinel-5P | No integration code. Public catalogue verified, processing path undecided. See below. |

Frontend check: the Environmental insights cards are keyed to the selected
coordinates. A retest in the live site after selecting another place showed new
PVGIS coordinates and the SPARTAN no_data state, so the earlier Delhi observation
was a snapshot timing artifact, not a defect. Regression assertions were added.

### Historical Weather optimization

Dry-run baseline on weather_insights.weather_history_in: 30d 0.987 GiB, 1y 12.13 GiB,
5y 35.28 GiB (earlier estimates). A later Delhi dry run on 2026-11-27 UTC
estimated 1,077,485,760 / 13,042,935,360 / 37,902,496,320 bytes for 30d/1y/5y;
all exceeded 1 GiB. No query was executed. The raw 30d path remains capped and
must return an unavailable state if it exceeds the limit. Quotas are not raised.
The following aggregate approach is a proposal only; do not execute its backfill
without explicit owner approval of the total processing/storage budget, verified
provider terms and project-wide quotas. Never partition a user request merely to
circumvent the 1 GiB cap.

1. scripts/build_weather_history_aggregate.sh creates
   weather_insights.weather_history_in_windows (clustered by lat, lng): half-month
   windows per grid point with hours, sum/min/max temperature, precipitation sum and
   humidity sum, de-duplicated to one row per grid point per hour. Each window is one
   INSERT, dry-run first, with --maximum_bytes_billed=1073741824. Windows with no raw
   rows get a sentinel row (0 hours) so they count as done. At most 4 windows per run
   by default (never more than 12). The project quota of 10 GiB/day is shared with
   live 30d queries (about 0.99 GiB per cache miss), so run off-peak and check the
   day's usage first. Completed windows are skipped, so it resumes across days.
   The 5y raw dry run is 35.28 GiB in total, so the one-time build is of that order
   (verify billing-account-wide use before claiming it is free).
2. Raw column names are assumed (geography, forecast_time, temperature_c, qpf_mm,
   relative_humidity_percent). Confirm with bq show --schema, or override with
   C_GEO, C_TIME, C_TEMP, C_RAIN, C_HUM. The dry run fails before billing on a mismatch.
3. server.mjs reads only that table for 1y and 5y with a 128 MiB ceiling (or a stricter configured cap). It serves a
   summary only when WEATHER_INSIGHTS_AGGREGATE_ENABLED=true and the table reaches
   back to the range start with every half-month window present, no tolerance except
   the newest 16 days (expectedWindows and aggregateComplete in aggregate.mjs).
   Empty windows count through sentinel rows. Responses carry coverageStart and
   coverageEnd (also coverage_start, coverage_end) from the observed rows and
   coveragePartial=true when observed data begins more than 31 days after the range
   start, which the widget shows in its existing coverage line. Otherwise it returns query_cost_cap_exceeded (422, missing table
   or disabled) or historical_aggregate_incomplete (503), never a raw scan or a
   partial summary labelled 1y/5y.
4. Differences to confirm before enabling the flag: the aggregate uses the nearest
   single grid point within 10 km, while the raw 30d path takes the nearest row per
   hour. --verify enforces this: it exits non-zero if any required window is missing
   or if the newest non-empty window's totals (grid points, hours, temperature sum,
   precipitation sum) differ from a fresh capped raw scan. Set the flag only after
   --verify passes. The SQL and script were checked here only by SQL parsing (sqlglot,
   BigQuery dialect) and a mocked bq run; they have not run against real BigQuery.

Cloud Shell, in this order:

    bash scripts/build_weather_history_aggregate.sh            # dry run
    # Only after explicit backfill approval and verified project quota:
    bash scripts/build_weather_history_aggregate.sh --apply
    bash scripts/build_weather_history_aggregate.sh --verify

The Cloud Run service must then be redeployed from gcp/vayulok-weather-insights,
and WEATHER_INSIGHTS_AGGREGATE_ENABLED=true set only after the comparison above.

### WeatherNext 3 (statistics Zarr)

Verified from Google documentation: gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/
holds precomputed _mean, _p10, _p25, _p50, _p75, _p90 for 0.1 and 0.05 degree surface
variables, with a flattened 1-hour lead_time axis and 360-hour horizon for 6-hourly
inits (hourly inits from 2026, 48-hour horizon). The statistics bucket is not
Requester Pays. Access is allowlist-only (form, reviewed in 5 to 7 business days);
anonymous listing returned 401 and an anonymous object read 403. Real-time data
(less than 1 hour old and future) falls under the Google DeepMind Real-Time Weather
Forecasting Experimental Data Terms of Use, which could not be read automatically
(PDF). Those terms, the allowlist status of the wecare account and the per-chunk byte
sizes are therefore unverified, and no code was added. P10/P50/P90 may be displayed
only after this is confirmed and only as WeatherNext 3 with its own attribution,
never from Google Weather. Do not query the BigQuery views.

Cloud Shell verification (read-only, lists names and reads zarr.json metadata only):

    bash scripts/verify_weathernext_statistics_access.sh

### Sentinel-5P

Verified: the Copernicus Data Space catalogue (OData, anonymous) returns current
TROPOMI L2 NO2 granules for Delhi, for example S5P_NRTI_L2__NO2____20261127T091052...nc
at 68 MB each; NO2, CO and aerosol index products exist as Non Time Critical (archive
from April 2018) and Near Real Time (last month). Downloads need a free Copernicus
Data Space account token. A 68 MB swath file per request exceeds the Lambda 6 MiB
upstream cap and cannot be cost-bounded per visitor, so it needs an offline
scheduled job that filters on qa_value, reduces to a small per-city JSON (time,
coverage, qa threshold, column value in mol/m2) and publishes it. That job and the
account are not created. Any display must say "satellite column, not surface
concentration". No code was added.

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
