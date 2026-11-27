#!/usr/bin/env bash
# Build the Nano Climate historical-weather aggregate in resumable, cost-capped chunks.
#
# Run in Google Cloud Shell as an owner/BigQuery Data Editor of project wecaredigitalbw:
#   bash scripts/build_weather_history_aggregate.sh            # dry run only (default)
#   bash scripts/build_weather_history_aggregate.sh --apply    # load up to MAX_CHUNKS windows
#   bash scripts/build_weather_history_aggregate.sh --verify   # read-only aggregate checks
#
# Safety:
# - Each chunk is one half-month window (about 0.5 GiB for the raw table). A dry run runs
#   first; a chunk is skipped if its estimate is not below 1 GiB.
# - Every load also sets --maximum_bytes_billed=1073741824, so BigQuery refuses to run it
#   if the estimate was wrong. Quotas are never changed.
# - MAX_CHUNKS (default 8, about 4 GiB) keeps one run far below the 10 GiB/day project
#   quota. Run again on following days; completed windows are skipped (resumable).
# - Only complete windows that ended before today (UTC) are loaded, one INSERT per window,
#   guarded by NOT EXISTS, so re-runs never duplicate rows.
# - The service (gcp/vayulok-weather-insights/server.mjs) only reads this aggregate for
#   1y and 5y ranges. 30d continues to read the raw table (0.987 GiB dry run).
set -euo pipefail

PROJECT="${PROJECT:-wecaredigitalbw}"
DATASET="${DATASET:-weather_insights}"
LOCATION="${LOCATION:-US}"
RAW="${PROJECT}.${DATASET}.weather_history_in"
AGG="${PROJECT}.${DATASET}.weather_history_in_windows"
YEARS="${YEARS:-5}"
MAX_CHUNKS="${MAX_CHUNKS:-8}"
CAP_BYTES=1073741824
MODE="dry-run"
[ "${1:-}" = "--apply" ] && MODE="apply"
[ "${1:-}" = "--verify" ] && MODE="verify"
[ "$MAX_CHUNKS" -ge 1 ] && [ "$MAX_CHUNKS" -le 12 ] || { echo "MAX_CHUNKS must be 1..12"; exit 2; }

bq_q() { bq --project_id="$PROJECT" --location="$LOCATION" query --use_legacy_sql=false --quiet "$@"; }

if [ "$MODE" = "verify" ]; then
  bq_q --format=prettyjson "
    SELECT COUNT(*) AS rows_loaded, COUNT(DISTINCT window_start) AS windows,
           MIN(window_start) AS first_window, MAX(window_start) AS last_window,
           COUNT(DISTINCT CONCAT(CAST(lat AS STRING), ',', CAST(lng AS STRING))) AS grid_points
    FROM \`${AGG}\`"
  exit 0
fi

# Aggregate table: tiny, clustered by location. Created only with --apply.
CREATE_SQL="CREATE TABLE IF NOT EXISTS \`${AGG}\` (
  lat FLOAT64, lng FLOAT64, window_start DATE, window_end DATE,
  sample_hours INT64, temp_sum FLOAT64, temp_min FLOAT64, temp_max FLOAT64,
  precip_sum FLOAT64, humidity_sum FLOAT64, humidity_n INT64,
  first_observed_at TIMESTAMP, last_observed_at TIMESTAMP, loaded_at TIMESTAMP
) CLUSTER BY lat, lng
OPTIONS (description='Half-month aggregates of weather_history_in for Nano Climate 1y/5y summaries')"
if [ "$MODE" = "apply" ]; then bq_q "$CREATE_SQL" >/dev/null; fi

# Half-month windows [start, end) that ended before today (UTC), newest first.
WINDOWS=$(python3 - "$YEARS" <<'PY'
import sys, datetime as d
years = int(sys.argv[1]); today = d.datetime.now(d.timezone.utc).date()
floor = today.replace(year=today.year - years)
out = []; y, m = today.year, today.month
while True:
    first = d.date(y, m, 1); mid = d.date(y, m, 16)
    nxt = d.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    for s, e in ((mid, nxt), (first, mid)):
        if e <= today and s >= floor: out.append(f"{s} {e}")
    m -= 1
    if m == 0: y, m = y - 1, 12
    if d.date(y, m, 1) < floor.replace(day=1): break
print("\n".join(out))
PY
)

DONE=""
if bq show "${AGG}" >/dev/null 2>&1; then
  DONE=$(bq_q --format=csv "SELECT CAST(window_start AS STRING) FROM \`${AGG}\` GROUP BY 1" | tail -n +2)
fi

insert_sql() { # $1=start $2=end
cat <<SQL
INSERT INTO \`${AGG}\`
SELECT
  ROUND(ST_Y(geography), 4) AS lat, ROUND(ST_X(geography), 4) AS lng,
  DATE '$1' AS window_start, DATE '$2' AS window_end,
  COUNT(*) AS sample_hours,
  SUM(SAFE_CAST(temperature_c AS FLOAT64)) AS temp_sum,
  MIN(SAFE_CAST(temperature_c AS FLOAT64)) AS temp_min,
  MAX(SAFE_CAST(temperature_c AS FLOAT64)) AS temp_max,
  SUM(SAFE_CAST(qpf_mm AS FLOAT64)) AS precip_sum,
  SUM(SAFE_CAST(relative_humidity_percent AS FLOAT64)) AS humidity_sum,
  COUNTIF(relative_humidity_percent IS NOT NULL) AS humidity_n,
  MIN(forecast_time) AS first_observed_at, MAX(forecast_time) AS last_observed_at,
  CURRENT_TIMESTAMP() AS loaded_at
FROM \`${RAW}\`
WHERE forecast_time >= TIMESTAMP '$1' AND forecast_time < TIMESTAMP '$2'
  AND temperature_c IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM \`${AGG}\` WHERE window_start = DATE '$1')
GROUP BY lat, lng
SQL
}

loaded=0; total_bytes=0
while read -r START END; do
  [ -n "${START:-}" ] || continue
  if printf '%s\n' "$DONE" | grep -qx "$START"; then continue; fi
  [ "$loaded" -lt "$MAX_CHUNKS" ] || { echo "Reached MAX_CHUNKS=$MAX_CHUNKS; run again tomorrow."; break; }
  SQL=$(insert_sql "$START" "$END")
  # The estimate is the identical raw scan without the aggregate-side NOT EXISTS guard.
  EST_SQL="SELECT ROUND(ST_Y(geography),4) AS lat, ROUND(ST_X(geography),4) AS lng, COUNT(*) AS n,
    SUM(SAFE_CAST(temperature_c AS FLOAT64)) AS t, SUM(SAFE_CAST(qpf_mm AS FLOAT64)) AS p,
    SUM(SAFE_CAST(relative_humidity_percent AS FLOAT64)) AS h, MIN(forecast_time) AS a, MAX(forecast_time) AS b
    FROM \`${RAW}\` WHERE forecast_time >= TIMESTAMP '$START' AND forecast_time < TIMESTAMP '$END'
    AND temperature_c IS NOT NULL GROUP BY lat, lng"
  BYTES=$(bq_q --dry_run --format=json "$EST_SQL" 2>&1 | python3 -c '
import json,re,sys
t=sys.stdin.read()
m=re.search(r"process (\d+) bytes",t) or re.search(r"\"totalBytesProcessed\": \"(\d+)\"",t)
print(m.group(1) if m else "")')
  if [ -z "$BYTES" ]; then echo "Dry run failed for $START; stopping."; exit 1; fi
  echo "window $START..$END dry-run bytes=$BYTES"
  if [ "$BYTES" -ge "$CAP_BYTES" ]; then echo "  skipped: estimate is not below 1 GiB"; continue; fi
  total_bytes=$((total_bytes + BYTES))
  [ "$MODE" = "apply" ] || continue
  bq_q --maximum_bytes_billed="$CAP_BYTES" "$SQL" >/dev/null
  echo "  loaded"
  loaded=$((loaded + 1))
done <<< "$WINDOWS"
echo "mode=$MODE windows_loaded=$loaded estimated_bytes_considered=$total_bytes"
[ "$MODE" = "apply" ] || echo "Dry run only. Re-run with --apply, then --verify."
