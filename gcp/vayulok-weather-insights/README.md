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
BQ_MAX_BYTES_BILLED=134217728
ALLOWED_ORIGINS=https://wecare.digital,https://www.wecare.digital
```

`WEATHER_INSIGHTS_TABLE` is optional when the linked dataset contains exactly one table/view.
If the dataset contains more than one, set the fully qualified table:

```
WEATHER_INSIGHTS_TABLE=publisher_or_subscriber_project.weather_insights.table_name
```

The adapter only auto-detects unit-explicit columns. If Google's experimental schema uses
different names, set these after inspecting the linked table:

```
WEATHER_INSIGHTS_TIME_COLUMN=observed_at
WEATHER_INSIGHTS_LAT_COLUMN=latitude
WEATHER_INSIGHTS_LNG_COLUMN=longitude
WEATHER_INSIGHTS_TEMP_C_COLUMN=temperature_c
WEATHER_INSIGHTS_RAIN_MM_COLUMN=precipitation_mm
WEATHER_INSIGHTS_HUMIDITY_PCT_COLUMN=relative_humidity_pct
```

Nested BigQuery field paths such as `location.latitude` are accepted.

## Cost guards

- BigQuery query cache is enabled.
- Each query has a hard `maximumBytesBilled` cap (128 MiB by default).
- Requests are cached in-process for six hours by 0.1-degree location cell and range.
- Per-instance request rate is limited.
- Deploy Cloud Run with `--max-instances=1` initially while validating actual bytes scanned.

If the query exceeds the byte cap, the service returns HTTP 422 instead of allowing an
unexpected large query.

## Existing Cloud Run service

The Google Cloud Console currently shows `wecare-digital` in `asia-south1` on Google's
placeholder image. To use that service for this adapter after the Analytics Hub linked dataset
exists:

```bash
gcloud run deploy wecare-digital \
  --source gcp/vayulok-weather-insights \
  --project wecaredigitalbw \
  --region asia-south1 \
  --allow-unauthenticated \
  --max-instances 1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=wecaredigitalbw,WEATHER_INSIGHTS_DATASET=weather_insights,BQ_LOCATION=US,BQ_MAX_BYTES_BILLED=134217728,ALLOWED_ORIGINS=https://wecare.digital
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
