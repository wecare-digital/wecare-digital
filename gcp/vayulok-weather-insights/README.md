# VayuLok Weather Insights Cloud Run service

This service is the server-side adapter between the public VayuLok page and the Google
Weather Insights linked dataset in BigQuery. It serves only long-term historical aggregates;
VayuLok's current Air, Weather, Maps, Places, Geocoding and Time Zone calls remain browser-side.

## Runtime contract

- `GET /healthz` — process health.
- `GET /v1/weather-insights/status` — linked dataset/table/schema readiness.
- `GET /v1/weather-insights?lat=25.5788&lng=91.8933&range=5y`
  - range: `30d`, `1y`, or `5y`
  - returns aggregate temperature, precipitation, humidity, and month-of-year trends
  - never returns a public year-by-year row set.

The service uses its Cloud Run service account through the metadata server. It accepts no
service-account JSON key and no Google API key.

## Required runtime environment

```
GOOGLE_CLOUD_PROJECT=wecaredigitalbw
WEATHER_INSIGHTS_DATASET=weather_insights
BQ_LOCATION=US
BQ_MAX_BYTES_BILLED_30D=1200000000
BQ_MAX_BYTES_BILLED_1Y=15000000000
BQ_MAX_BYTES_BILLED_5Y=40000000000
ALLOWED_ORIGINS=https://wecare.digital,https://wecare.digital
```

The subscribed India listing currently exposes:
`wecaredigitalbw.weather_insights.weather_history_in`.

The adapter auto-detects the current linked-view schema. The existing
`WEATHER_INSIGHTS_*_COLUMN` overrides remain available if the publisher changes field names.

## Cost guards

- BigQuery query cache is enabled.
- 30D / 1Y / 5Y each have a hard `maximumBytesBilled` cap.
- Results are cached in-process for 24 hours by location and range.
- The UI defaults to 30D; 1Y and 5Y require an explicit visitor choice.
- Keep `--max-instances=1` while validating real query cost.

A query that exceeds its byte cap returns HTTP 422 rather than scanning beyond the guard.

## Production deploy

The production Cloud Run service is `wecare-digital` in `asia-south1`.
`gcp/vayulok-weather-insights/cloudbuild.yaml` syntax-checks `server.mjs`, then builds,
pushes and updates that existing service. It deliberately does not change the service account,
IAM policy or runtime environment.

**Trigger configuration is external to this repository.** The Cloud Build trigger should:

- watch only the production branch `^wecare\\.digital$`
- use `gcp/vayulok-weather-insights/cloudbuild.yaml`
- include only changes under `gcp/vayulok-weather-insights/**`

The last item prevents an unrelated frontend/test-only commit from redeploying the Cloud Run
adapter. Editing this README or `cloudbuild.yaml` cannot change the trigger's include-files
filter; update that setting in Cloud Build trigger configuration.

For a manual deploy:

```bash
gcloud run deploy wecare-digital \
  --source ./gcp/vayulok-weather-insights \
  --project wecaredigitalbw \
  --region asia-south1 \
  --max-instances 1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=wecaredigitalbw,WEATHER_INSIGHTS_DATASET=weather_insights,BQ_LOCATION=US,ALLOWED_ORIGINS=https://wecare.digital
```

After deploy:

```bash
SERVICE_URL="$(gcloud run services describe wecare-digital --project wecaredigitalbw --region asia-south1 --format='value(status.url)')"
curl -sS "$SERVICE_URL/healthz"
curl -sS "$SERVICE_URL/v1/weather-insights/status" | python3 -m json.tool
```

## Frontend endpoint configuration

The frontend reads `NEXT_PUBLIC_VAYULOK_WEATHER_INSIGHTS_URL`; the component does not embed
a generated Cloud Run hostname. Production's Amplify build supplies the current service origin.
Local development can set the same variable in `.env.local`.

The endpoint is public configuration, not a credential.

## Dataset note

The Analytics Hub subscription is active in `US`; the linked dataset is `LINKED`, and the
published view carries `RESTRICTED_DATA_EGRESS`. The adapter queries it in place and returns
only aggregate JSON. Provider history currently starts in 2024, so the UI reports actual
coverage and describes the 5Y view as a month-of-year aggregate rather than promising five
complete calendar years.
