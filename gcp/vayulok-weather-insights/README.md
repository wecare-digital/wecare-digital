# VayuLok Weather Insights Cloud Run service

This service is the server-side adapter between the public VayuLok page and the Google
Weather Insights linked dataset in BigQuery.

It does **not** replace VayuLok's browser-side Google Weather API, Air Quality API, Maps,
Places, Geocoding or Time Zone calls. It serves only long-term historical aggregates.

## Runtime contract

- `GET /healthz` - process health only.
- `GET /v1/weather-insights/status` - verifies whether the linked dataset/table/schema is ready.
- `GET /v1/weather-insights?lat=25.5788&lng=91.8933&range=5y`
  - range is `30d`, `1y` or `5y`.
  - returns aggregate temperature, precipitation, humidity and month-of-year trends.
  - never returns year-by-year public rows.

The service uses the Cloud Run service account through the metadata server. No service-account
JSON key or Google API key is accepted.

## Required environment

```
GOOGLE_CLOUD_PROJECT=wecaredigitalbw
WEATHER_INSIGHTS_DATASET=weather_insights
BQ_LOCATION=US
BQ_MAX_BYTES_BILLED_30D=1200000000
BQ_MAX_BYTES_BILLED_1Y=9500000000
BQ_MAX_BYTES_BILLED_5Y=40000000000
ALLOWED_ORIGINS=https://wecare.digital,https://www.wecare.digital
```

The subscribed India listing currently exposes one linked view:

```
wecaredigitalbw.weather_insights.weather_history_in
```

The adapter auto-detects Google's current schema: `forecast_time`, `geography`,
`temperature_c`, `qpf_mm`, and `relative_humidity_percent`. If the experimental schema
changes later, the corresponding `WEATHER_INSIGHTS_*_COLUMN` environment overrides remain
available. Nested field paths are accepted.

## Cost guards

- BigQuery query cache is enabled.
- Each range has its own hard `maximumBytesBilled` cap. Current defaults are 1.2 GB for
  30D, 9.5 GB for 1Y, and 40 GB for 5Y, based on dry runs against the linked India view.
- Requests are cached in-process for 24 hours by location and range.
- The UI defaults to 30D; 1Y and 5Y are explicit user choices, so the most expensive query is
  never fired merely by opening the Weather tab.
- BigQuery query cache remains enabled for repeated identical requests.
- Per-instance request rate is limited.
- Deploy Cloud Run with `--max-instances=1` initially while validating actual bytes scanned.

If the query exceeds the byte cap, the service returns HTTP 422 instead of allowing an
unexpected large query.

## Existing Cloud Run service

The Google Cloud Console currently shows `wecare-digital` in `asia-south1` on Google's
placeholder image. To use that service for this adapter after the Analytics Hub linked dataset
exists:

```bash
# Run from the repository root.
gcloud run deploy wecare-digital \
  --source ./gcp/vayulok-weather-insights \
  --project wecaredigitalbw \
  --region asia-south1 \
  --max-instances 1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=wecaredigitalbw,WEATHER_INSIGHTS_DATASET=weather_insights,BQ_LOCATION=US,ALLOWED_ORIGINS=https://wecare.digital
```

Before public traffic, grant the Cloud Run runtime service account the minimum BigQuery job
permission on `wecaredigitalbw` and read access to the linked dataset. Do not grant Owner.

After deploy:

```bash
SERVICE_URL="$(gcloud run services describe wecare-digital --project wecaredigitalbw --region asia-south1 --format='value(status.url)')"
curl -sS "$SERVICE_URL/healthz"
curl -sS "$SERVICE_URL/v1/weather-insights/status" | python3 -m json.tool
```

When status is ready, set the Amplify build-time variable:

```
NEXT_PUBLIC_VAYULOK_INSIGHTS_URL=<Cloud Run service URL>
```

and redeploy the `stack` branch so the static VayuLok bundle receives the endpoint.


## Verified India listing

The Analytics Hub subscription is active in `US`, the linked dataset type is `LINKED`,
and the published view is `weather_history_in`. The linked dataset carries
`RESTRICTED_DATA_EGRESS`, so this service queries it in place and returns only aggregate JSON;
it does not copy or export the publisher dataset.

The listing documentation states historical availability starts in 2024. The public UI therefore
shows the actual returned coverage dates instead of claiming a full five calendar years when the
provider does not currently supply them.
