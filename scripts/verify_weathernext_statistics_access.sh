#!/usr/bin/env bash
# Read-only WeatherNext 3 statistics access check. Run in Google Cloud Shell as the
# Google account (or service account) that was submitted on the WeatherNext data request form.
#   bash scripts/verify_weathernext_statistics_access.sh
# It lists names and reads small metadata files only. It never opens a data array chunk,
# never runs BigQuery, and never creates a resource.
set -euo pipefail
BASE="gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr"
echo "Account: $(gcloud config get-value account 2>/dev/null)"
echo "1) Access (expects a listing; 403 means the account is not allowlisted yet)"
gcloud storage ls "${BASE}/2026_to_present/" 2>&1 | tail -n 3
LATEST=$(gcloud storage ls "${BASE}/2026_to_present/" | sort | tail -n 1)
echo "Latest init folder: ${LATEST}"
echo "2) Store metadata (Zarr v3 zarr.json files are small)"
gcloud storage cat "${LATEST}predictions.zarr/zarr.json" | head -c 3000; echo
echo "3) Array names and total stored size per variable of interest (metadata listing only)"
gcloud storage ls "${LATEST}predictions.zarr/" | grep -E "temperature_2m|total_precipitation|2m_temperature|lead_time|lat_0p1|lon_0p1" || true
echo "4) Chunk shape of a temperature P10/P50/P90 array (replace NAME after step 3)"
echo "   gcloud storage cat \"${LATEST}predictions.zarr/NAME/zarr.json\" | python3 -c 'import json,sys; m=json.load(sys.stdin); print(m[\"shape\"], m.get(\"chunk_grid\"), m.get(\"data_type\"))'"
echo "Record: allowlisted account, chunk shape, bytes per chunk, init cadence. Do not paste credentials."
