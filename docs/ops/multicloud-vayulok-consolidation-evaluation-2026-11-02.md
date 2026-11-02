# Multi-cloud VayuLok Consolidation Evaluation (gcp/vayulok-weather-insights)

- **Scope:** Strategic, evaluate-only, **source-only**. This document decides whether the GCP Cloud Run weather-insights service should be consolidated onto AWS or left as-is. It changes no code and no configuration. It belongs to Phase 5 ("Strategic, evaluate only") of `architecture/workspace-audit-2026-11-02.md` section 6, and relates to audit sections 2.7 and 5f.
- **Date:** 2026-11-02
- **Execution status:** **BLOCKED on GCP access.** No GCP call was made or should be made to produce this document. The live dataset size, actual query costs, quotas, and billing cannot be inventoried from here. The analysis below is strictly from source files in this repository. Any consolidation would be a separate initiative that first requires GCP access.
- **Primary source files cited:** `gcp/vayulok-weather-insights/server.mjs`, `gcp/vayulok-weather-insights/cloudbuild.yaml`, `gcp/vayulok-weather-insights/Dockerfile`, `scripts/vayulok_gcp_activate.sh`, `scripts/check_vayulok_cost_and_map.cjs`, `scripts/provision_vayulok_environment.py`, `amplify.yml`, `.env.example`, `.env.local.example`, `src/components/VayuLokLive.tsx`, `src/components/VayuLokWeatherInsights.tsx`.
- **Identifiers:** This is a public repository. Concrete GCP project ids/numbers, Cloud Run URLs, AWS account ids, ARNs, and keys are referred to generically here ("the GCP project", "the AWS account", "the Cloud Run service") and are intentionally not reproduced, even though some provisioning scripts contain them.

## 1. What the service does

`gcp/vayulok-weather-insights/server.mjs` is a small Node `http` service with no web framework. It exposes three endpoints:

- `GET /healthz`
- `GET /v1/weather-insights/status`
- `GET /v1/weather-insights?lat&lng&range=30d|1y|5y`

It serves **long-term historical weather aggregates** by querying **BigQuery** (dataset `weather_insights`) with BigQuery GIS SQL (`ST_GEOGPOINT`, `ST_DWITHIN`, `ST_DISTANCE`) over a weather-history table. It authenticates to Google APIs via the **GCP metadata server** (`metadata.google.internal` service-account token), that is, Cloud Run workload identity with no stored key.

It is engineered around free-tier cost safety, verifiable in the source:

- `HARD_MAX_BYTES_PER_QUERY = 1073741824n` (1 GiB per query); higher environment values cannot bypass this absolute ceiling (`boundedQueryBytes`).
- A per-instance daily attempt budget (`INSTANCE_MAX_DAILY_QUERY_ATTEMPTS`, default 8, hard max 12) via `reserveQueryBudget()`.
- A 0.1-degree grid cache, in-flight request coalescing (`inFlight`), and per-minute rate limiting (`RATE_LIMIT_PER_MINUTE`, default 30).
- CORS locked by default to `https://wecare.digital` (`ALLOWED_ORIGINS`).

The source itself notes that AWS Amplify builds do not deploy this service; `cloudbuild.yaml` is its deployment path.

## 2. How it is built and deployed (GCP side)

- `gcp/vayulok-weather-insights/cloudbuild.yaml`: Cloud Build checks `server.mjs`, builds a Docker image, pushes it to Artifact Registry in `asia-south1`, and deploys/updates a Cloud Run service in region `asia-south1`.
- `gcp/vayulok-weather-insights/Dockerfile`: `FROM node:24-alpine`, runs as the non-root `node` user, copies only `package.json` and `server.mjs`, a deliberately minimal image.
- `scripts/vayulok_gcp_activate.sh`: read-only by default; `--apply` **lowers (never raises)** the BigQuery project `QueryUsagePerDay` quota to at most 10 GiB/day and deploys the reviewed Cloud Run backend. It pins and verifies a `SOURCE_SHA` of `server.mjs` (git blob hash) before deploying, and refuses to run off the production branch. Google Maps quota controls are intentionally **not** changed by this script.

The region choice (`asia-south1`, India) matches the India-focused product.

## 3. The cross-cloud build guard (why the GCP source lives in this repo)

`scripts/check_vayulok_cost_and_map.cjs` runs inside the **AWS Amplify production build** (`amplify.yml`, the `node scripts/check_vayulok_cost_and_map.cjs` step). It reads and cross-validates, together:

- the frontend: `src/components/VayuLokLive.tsx` and `src/components/VayuLokWeatherInsights.tsx`, and
- the GCP backend: `gcp/vayulok-weather-insights/server.mjs`, and
- the AWS gateway provisioner: `scripts/provision_vayulok_environment.py`.

It asserts the 1 GiB BigQuery per-query cap, the daily attempt budget, in-flight coalescing, the India map bounds, that paid Google heatmap tiles are off by default, and that the AWS gateway throttle stays at the audited 2 rps / 4 burst. So although AWS does not deploy the GCP service, the AWS build **contract-checks** the GCP source on every production build. The two clouds are coupled by a shared safety contract that lives in this one repo.

## 4. Why VayuLok spans two clouds by design (complementary, not redundant)

VayuLok is intentionally split across two providers, and the two halves do different jobs:

- **AWS side (live / near-term):** a Lambda gateway `wecare-vayulok-environment` (provisioned by `scripts/provision_vayulok_environment.py`) fronts Google Maps Platform APIs (Places, Geocoding, Address Validation, Weather, Air Quality) using a server-side, referrer-locked, non-public Google key read from a secret. `.env.example` is explicit about why this cannot be a `NEXT_PUBLIC_*` browser key: `output: 'export'` inlines `NEXT_PUBLIC_*` values into the public HTML, so these credentials must stay server-side in a Lambda, never in the client bundle. This half serves the live map, air-quality, and near-term weather.
- **GCP side (long-term history):** the Cloud Run service serves long-term historical aggregates (30d / 1y / 5y) from BigQuery. The frontend reaches it through `NEXT_PUBLIC_VAYULOK_WEATHER_INSIGHTS_URL` (`.env.local.example`), which is an **endpoint URL, not a credential**, safe to inline because it exposes no secret.

These are complementary data planes (live Google Maps/AQI/weather via AWS vs. historical BigQuery aggregates via GCP), not two implementations of the same thing.

## 5. Data gravity and the economics that pin it to GCP

The reasons the historical service plausibly belongs on GCP are structural, not incidental:

- **The data lives in BigQuery** (dataset `weather_insights`) inside a GCP project. The weather-history data has gravity; the query engine sits next to the data.
- **BigQuery GIS** (`ST_GEOGPOINT`, `ST_DWITHIN`, `ST_DISTANCE`) is the query engine. Reproducing geospatial aggregation at comparable cost elsewhere is not trivial.
- **Free-tier economics**: the whole service is built around BigQuery's free-tier query allowance, enforced by the 1 GiB per-query cap and the daily attempt budget. That economic model is specific to BigQuery.
- **Keyless auth**: Cloud Run workload identity (metadata-server token) means there is no stored key to manage or rotate.
- **Region**: the Cloud Run service and its Artifact Registry image are in `asia-south1` (per `cloudbuild.yaml`), co-locating the compute with the India-focused product. Note the BigQuery data location is not established as `asia-south1`: `server.mjs` sets `LOCATION = process.env.BQ_LOCATION || 'US'`, so the dataset defaults to `US` unless `BQ_LOCATION` is overridden. The data-gravity argument below rests on the data living in BigQuery at all, not on its region.

## 6. The tradeoffs the audit raised (sections 2.7, 5f)

A second cloud provider is not free operationally:

- **Onboarding cost:** engineers must understand two clouds, two deployment models (AWS Amplify + imperative scripts vs. Google Cloud Build + Cloud Run), and two auth models.
- **Bus-factor risk:** operational knowledge is concentrated in a few bespoke scripts (`scripts/vayulok_gcp_activate.sh`, `cloudbuild.yaml`) and in one person's understanding of the GCP project. If that knowledge is lost, redeploying or adjusting the service is hard.
- **Runbook / ownership gaps:** the activation path is guarded and documented in-script, but there is no standalone ownership/runbook document for the GCP service.

These are real costs and the honest side of the "keep it" case.

## 7. Options (with honest tradeoffs)

### Option 1: Consolidate to AWS

Reimplement the historical service on AWS (for example, Lambda + Athena/Redshift over S3, or migrate the dataset into an AWS data store).

- **Costs:** reimplement BigQuery GIS logic on a different engine (Athena geospatial / Redshift / custom), migrate the weather-history dataset, lose the BigQuery free-tier economics the current guards are tuned to, and re-home the keyless workload-identity auth model to an AWS equivalent. The frontend contract and the cross-cloud guard would both need rework.
- **Benefit:** a single cloud, lower bus-factor and onboarding cost, one deployment model.
- **Blocker:** cannot be scoped or costed without GCP access to inventory the dataset, query volumes, and actual spend.

### Option 2: Keep the split as-is

Leave the GCP Cloud Run service where it is.

- **Costs:** accept the two-cloud bus-factor and onboarding overhead from section 6.
- **Benefit:** preserves data gravity (data stays next to the query engine), keeps the working free-tier guards and keyless auth, and keeps the existing cross-cloud build guard intact. No migration risk.

### Option 3: Keep data in BigQuery, front it from AWS

Leave the weather-history data in BigQuery but put an AWS-hosted facade (e.g. a Lambda) in front of it.

- **Costs:** this still straddles two clouds (so it does not remove the bus-factor cost), and it adds cross-cloud **egress** and latency on every query, plus a second credential/auth hop from AWS into GCP. It also loses the simplicity of the current single-hop Cloud Run service.
- **Benefit:** centralizes the public entry point on AWS without migrating the data.

## 8. Recommendation

**Keep as-is. Defer consolidation.**

Rationale, grounded in the source:

- The service is **small and self-contained** (`server.mjs`, one `package.json`, a minimal `node:24-alpine` image), **source-controlled in this repo**, and **contract-checked by the AWS production build** via `scripts/check_vayulok_cost_and_map.cjs` in `amplify.yml`. It is not an unmanaged shadow system.
- It sits on top of **BigQuery data gravity + BigQuery GIS + free-tier economics + keyless Cloud Run workload identity** in the India region. AWS cannot cheaply replicate that combination, so Option 1 and Option 3 both pay a real reimplementation/egress cost for a service whose whole design is tuned to BigQuery's free tier.
- The two clouds are **complementary by design** (live Google Maps/AQI/weather via the AWS Lambda gateway vs. long-term BigQuery history via Cloud Run), not redundant, so consolidation does not remove duplicate work; it moves a working service to a worse-fitting platform.

If consolidation is ever pursued, it must be a **separate initiative** and is **blocked on GCP access** today: the live dataset size, query volumes, quotas, and actual costs cannot be inventoried from this repository, and those numbers are prerequisites for an honest cost/benefit decision.

**Low-cost interim hygiene (no GCP access required):**

- Write a short ownership/runbook document for the GCP service (what it is, who owns it, how `scripts/vayulok_gcp_activate.sh --check` / `--apply` is used, and the `cloudbuild.yaml` deploy path), so the operational knowledge is not only in scripts.
- Record the two-cloud bus-factor risk explicitly in the ops risk register (per audit sections 2.7 / 5f).
- Keep the cross-cloud build guard (`scripts/check_vayulok_cost_and_map.cjs`) in `amplify.yml` as the standing safety contract that ties the two clouds together.

This is a decision with rationale: the evidence favors keeping the split and deferring any consolidation until there is a product reason and GCP access to scope it properly.
